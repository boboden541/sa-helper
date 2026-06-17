"""LinkerMixin — methods that create relationships between existing nodes."""

from __future__ import annotations

import re

# Code->DB inventory resolver (T2) ------------------------------------------------

# Minimum length of an inventory name to consider (guards against short English
# words that happen to be table names like "id"/"job").
RESOLVER_MIN_NAME_LEN = 4

# Identifier tokens inside a SQL fragment.
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# Allowed relationship types (also the order is the routing priority). These are
# internal constants and are the ONLY values interpolated into Cypher.
_RESOLVER_REL_TYPES = {"QUERIES", "INSERTS_INTO", "UPDATES", "DELETES_FROM", "CALLS_SP"}
_RESOLVER_LABELS = {"Table", "View", "StoredProcedure"}

# Keyword immediately preceding a name (tail-anchored) → (rel_type). Matching the
# tail means the name is adjacent to the keyword → higher confidence.
_ADJACENT_ROUTES = [
    (re.compile(r"DELETE\s+FROM[\s`\"'\[\(]*$", re.IGNORECASE), "DELETES_FROM"),
    (re.compile(r"INSERT\s+INTO[\s`\"'\[\(]*$", re.IGNORECASE), "INSERTS_INTO"),
    (re.compile(r"\bINTO[\s`\"'\[\(]*$", re.IGNORECASE), "INSERTS_INTO"),
    (re.compile(r"\bUPDATE[\s`\"'\[\(]*$", re.IGNORECASE), "UPDATES"),
    (re.compile(r"\bFROM[\s`\"'\[\(]*$", re.IGNORECASE), "QUERIES"),
    (re.compile(r"\bJOIN[\s`\"'\[\(]*$", re.IGNORECASE), "QUERIES"),
    (re.compile(r"\bEXEC(?:UTE)?[\s`\"'\[\(\.]*$", re.IGNORECASE), "CALLS_SP"),
    (re.compile(r"\bCALL[\s`\"'\[\(\.]*$", re.IGNORECASE), "CALLS_SP"),
]

# Same keywords, unanchored — used to classify a name that is in the SQL window
# but not directly adjacent to a keyword (lower confidence).
_NEARBY_ROUTES = [
    (re.compile(r"DELETE\s+FROM", re.IGNORECASE), "DELETES_FROM"),
    (re.compile(r"INSERT\s+INTO", re.IGNORECASE), "INSERTS_INTO"),
    (re.compile(r"\bEXEC(?:UTE)?\b", re.IGNORECASE), "CALLS_SP"),
    (re.compile(r"\bCALL\b", re.IGNORECASE), "CALLS_SP"),
    (re.compile(r"\bUPDATE\b", re.IGNORECASE), "UPDATES"),
    (re.compile(r"\bINTO\b", re.IGNORECASE), "INSERTS_INTO"),
    (re.compile(r"\bFROM\b", re.IGNORECASE), "QUERIES"),
    (re.compile(r"\bJOIN\b", re.IGNORECASE), "QUERIES"),
]

# Context window (chars) scanned before a name to find its governing SQL keyword.
_RESOLVER_CONTEXT_WINDOW = 48


def _route_rel_from_context(before: str) -> tuple[str | None, bool]:
    """Determine the edge type for a name from the SQL text preceding it.

    Returns (rel_type, adjacent). `adjacent` is True when a routing keyword sits
    directly before the name (medium confidence); False when the keyword is only
    somewhere in the window (low confidence). (None, False) means no SQL keyword
    governs this name — the caller should skip it as noise.
    """
    for pattern, rel in _ADJACENT_ROUTES:
        if pattern.search(before):
            return rel, True
    # Not adjacent: pick the keyword nearest to the name (max end position).
    best_rel = None
    best_pos = -1
    for pattern, rel in _NEARBY_ROUTES:
        for m in pattern.finditer(before):
            if m.end() > best_pos:
                best_pos = m.end()
                best_rel = rel
    return best_rel, False


class LinkerMixin:

    def link_config_to_classes(self):
        """Link ConfigEntry to classes that use the same infrastructure."""
        with self.driver.session() as session:
            session.run(
                """
                MATCH (ce:ConfigEntry {type: 'db'})
                MATCH (f:Function)-[:QUERIES]->(t:Table)
                WHERE f.file STARTS WITH split(ce.file, '/')[0]
                WITH DISTINCT ce, f
                MERGE (ce)-[:CONFIGURES {confidence: 'low'}]->(f)
                """
            )
            session.run(
                """
                MATCH (ce:ConfigEntry)
                WHERE ce.type IN ['redis', 'cache']
                MATCH (f:Function)-[:USES_FRAMEWORK]->(fw:FrameworkComponent)
                WHERE toLower(fw.name) CONTAINS 'cache'
                WITH DISTINCT ce, f
                MERGE (ce)-[:CONFIGURES {confidence: 'medium'}]->(f)
                """
            )
            session.run(
                """
                MATCH (fc:FrameworkComponent)
                WHERE fc.source_file IS NOT NULL
                MATCH (c:Class)
                WHERE toLower(c.name) = toLower(fc.name)
                SET fc.class_file = c.file
                """
            )
            session.run(
                """
                MATCH (fc:FrameworkComponent), (ce:ConfigEntry)
                WHERE ce.value CONTAINS fc.name
                AND size(fc.name) >= 3
                AND ce.source_file CONTAINS '/'
                SET fc.config_file = ce.source_file
                """
            )
            session.run(
                """
                MATCH (ce:ConfigEntry {type: 'db'})
                WITH ce, split(ce.key, '.')[0] AS db_prefix
                WHERE size(db_prefix) >= 3
                MATCH (c:Class)
                WHERE toLower(c.name) CONTAINS toLower(db_prefix)
                WITH ce, c LIMIT 10
                MATCH (c)-[:HAS_METHOD]->(f:Function)
                WITH DISTINCT ce, f
                MERGE (ce)-[:CONFIGURES {confidence: 'high'}]->(f)
                """
            )

    def mark_dynamic_sql(self):
        with self.driver.session() as session:
            session.run(
                """
                MATCH (f:Function)-[:USES_FRAMEWORK]->(fw:FrameworkComponent {name: 'createCommand'})
                WHERE NOT (f)-[:QUERIES]->(:Table)
                AND NOT (f)-[:CALLS_SP]->(:StoredProcedure)
                SET f.has_dynamic_sql = true
                """
            )

    def resolve_code_db_inventory(self, candidates: list[dict],
                                  default_schema: str | None = None) -> dict:
        """MATCH-only code->DB resolver (T2).

        Matches SQL-candidate fragments from functions against the DDL inventory
        already in the graph, then creates QUERIES/INSERTS_INTO/UPDATES/
        DELETES_FROM/CALLS_SP edges via MATCH to the existing DDL node — never
        MERGE-ing the DDL node, so no phantom nodes are created. New edges carry
        confidence (low/medium) and source='inventory_resolver'; pre-existing
        precise edges keep priority (ON CREATE only). Functions whose candidates
        resolve to nothing stay marked has_dynamic_sql.

        When a name exists in several schemas and the code reference is unqualified,
        the default schema is preferred (avoids fan-out to every same-named object).
        """
        if not candidates:
            return {"edges": 0, "marked_dynamic": 0}

        # Lazy import — keeps tree-sitter out of the query-only server path.
        from parsers.sql_utils import SQL_FALSE_POSITIVES, SQL_KEYWORDS

        def _token_ok(tok: str) -> bool:
            if len(tok) < RESOLVER_MIN_NAME_LEN:
                return False
            upper = tok.upper()
            if upper in SQL_KEYWORDS or upper in SQL_FALSE_POSITIVES:
                return False
            return True

        with self.driver.session() as session:
            # 1. Load DDL inventory (existing nodes only).
            table_inv: dict[str, list[dict]] = {}
            sp_inv: dict[str, list[dict]] = {}
            inv_result = session.run(
                """
                MATCH (n)
                WHERE n:Table OR n:View OR n:StoredProcedure
                RETURN labels(n)[0] AS label, n.schema AS schema, n.name AS name
                """
            )
            for rec in inv_result:
                if not rec["name"]:
                    continue
                entry = {"label": rec["label"], "schema": rec["schema"], "name": rec["name"]}
                low = rec["name"].lower()
                if rec["label"] == "StoredProcedure":
                    sp_inv.setdefault(low, []).append(entry)
                else:
                    table_inv.setdefault(low, []).append(entry)

            funcs_with_candidates = {
                (c["function_name"], c["file"]) for c in candidates
                if c.get("function_name") and c.get("file")
            }

            if table_inv or sp_inv:
                # 2. Match candidates against the inventory.
                # edge_map: (func_name, func_file, rel, label, schema, name) -> confidence
                edge_map: dict[tuple, str] = {}

                for cand in candidates:
                    func_name = cand.get("function_name")
                    func_file = cand.get("file")
                    fragment = cand.get("fragment") or ""
                    if not func_name or not func_file or not fragment:
                        continue

                    for match in _IDENT_RE.finditer(fragment):
                        low = match.group(0).lower()
                        if low not in table_inv and low not in sp_inv:
                            continue
                        if not _token_ok(match.group(0)):
                            continue

                        before = fragment[max(0, match.start() - _RESOLVER_CONTEXT_WINDOW):match.start()]
                        rel, adjacent = _route_rel_from_context(before)
                        if rel is None:
                            continue  # no governing SQL keyword — skip as noise

                        targets = sp_inv.get(low) if rel == "CALLS_SP" else table_inv.get(low)
                        if not targets:
                            continue  # name not in the inventory matching this edge type

                        # Unqualified name in several schemas → prefer default schema
                        # instead of fanning out to every same-named object.
                        if len(targets) > 1 and default_schema:
                            preferred = [t for t in targets if t["schema"] == default_schema]
                            if preferred:
                                targets = preferred

                        confidence = "medium" if adjacent else "low"
                        for tgt in targets:
                            key = (func_name, func_file, rel, tgt["label"],
                                   tgt["schema"], tgt["name"])
                            if edge_map.get(key) == "medium":
                                continue
                            edge_map[key] = confidence

                # 3. Group edges by (rel, label) and write them MATCH-only.
                groups: dict[tuple, list[dict]] = {}
                for (func_name, func_file, rel, label, schema, name), conf in edge_map.items():
                    if rel not in _RESOLVER_REL_TYPES or label not in _RESOLVER_LABELS:
                        continue
                    groups.setdefault((rel, label), []).append({
                        "func_name": func_name, "func_file": func_file,
                        "schema": schema, "name": name, "confidence": conf,
                    })

                for (rel, label), rows in groups.items():
                    query = (
                        "UNWIND $rows AS row "
                        "MATCH (f:Function {name: row.func_name, file: row.func_file}) "
                        f"MATCH (t:{label}) "
                        "WHERE t.name = row.name AND "
                        "(t.schema = row.schema OR (t.schema IS NULL AND row.schema IS NULL)) "
                        f"MERGE (f)-[r:{rel}]->(t) "
                        "ON CREATE SET r.confidence = row.confidence, "
                        "r.source = 'inventory_resolver'"
                    )
                    for chunk in self._chunks(rows):
                        session.run(query, rows=chunk)

            # 4. Mark / unmark has_dynamic_sql for candidate-bearing functions.
            func_rows = [{"name": n, "file": f} for (n, f) in funcs_with_candidates]
            marked = 0
            for chunk in self._chunks(func_rows):
                # Clear the flag where a code->DB edge now exists.
                session.run(
                    """
                    UNWIND $funcs AS fn
                    MATCH (f:Function {name: fn.name, file: fn.file})
                    WHERE f.has_dynamic_sql = true
                      AND (f)-[:QUERIES|CALLS_SP|INSERTS_INTO|UPDATES|DELETES_FROM]->()
                    SET f.has_dynamic_sql = false
                    """,
                    funcs=chunk,
                )
                # Mark functions that still have no resolved target.
                res = session.run(
                    """
                    UNWIND $funcs AS fn
                    MATCH (f:Function {name: fn.name, file: fn.file})
                    WHERE NOT (f)-[:QUERIES|CALLS_SP|INSERTS_INTO|UPDATES|DELETES_FROM]->()
                    SET f.has_dynamic_sql = true
                    RETURN count(f) AS cnt
                    """,
                    funcs=chunk,
                )
                marked += res.single()["cnt"]

            # True count of resolver edges (only those it created carry the source).
            edge_count = session.run(
                "MATCH ()-[r]->() WHERE r.source = 'inventory_resolver' "
                "RETURN count(r) AS cnt"
            ).single()["cnt"]

            return {"edges": edge_count, "marked_dynamic": marked}

    def link_cross_project(self):
        """Create cross-project dependency network from existing graph relationships.

        Derives project names from file path prefixes — no hardcoded names.
        """
        with self.driver.session() as session:
            # 1. Code projects sharing DB objects
            session.run("""
                MATCH (a:Function)-[:QUERIES|INSERTS_INTO|UPDATES]->(target)
                MATCH (b:Function)-[:QUERIES|INSERTS_INTO|UPDATES]->(target)
                WHERE split(a.file, '/')[0] <> split(b.file, '/')[0]
                WITH split(a.file, '/')[0] AS proj_a, split(b.file, '/')[0] AS proj_b,
                     labels(target)[0] AS target_type,
                     collect(DISTINCT target.name) AS shared_objects
                MERGE (pa:Project {name: proj_a})
                MERGE (pb:Project {name: proj_b})
                MERGE (pa)-[:SHARES_DATA_WITH {objects: shared_objects, type: target_type}]->(pb)
            """)

            # 2. Code → DB: Function calls SP from another project
            session.run("""
                MATCH (f:Function)-[:CALLS_SP]->(sp:StoredProcedure)
                WHERE split(f.file, '/')[0] <> split(sp.source_file, '/')[0]
                  AND sp.source_file IS NOT NULL
                WITH split(f.file, '/')[0] AS code_proj,
                     split(sp.source_file, '/')[0] AS sp_proj,
                     collect(DISTINCT sp.name) AS sp_names
                MERGE (cp:Project {name: code_proj})
                MERGE (dp:Project {name: sp_proj})
                MERGE (cp)-[:CALLS_SP {procedures: sp_names}]->(dp)
            """)

            # 3. Code → DB: Function uses Table from another project
            session.run("""
                MATCH (f:Function)-[:QUERIES]->(t:Table)
                WHERE split(f.file, '/')[0] <> split(t.source_file, '/')[0]
                  AND t.source_file IS NOT NULL
                WITH split(f.file, '/')[0] AS code_proj,
                     split(t.source_file, '/')[0] AS table_proj,
                     count(DISTINCT t.name) AS table_count
                MERGE (cp:Project {name: code_proj})
                MERGE (dp:Project {name: table_proj})
                MERGE (cp)-[:USES_TABLES {count: table_count}]->(dp)
            """)

            # 4. Code → DB: Function uses View from another project
            session.run("""
                MATCH (f:Function)-[:QUERIES]->(v:View)
                WHERE split(f.file, '/')[0] <> split(v.source_file, '/')[0]
                  AND v.source_file IS NOT NULL
                WITH split(f.file, '/')[0] AS code_proj,
                     split(v.source_file, '/')[0] AS view_proj,
                     count(DISTINCT v.name) AS view_count
                MERGE (cp:Project {name: code_proj})
                MERGE (dp:Project {name: view_proj})
                MERGE (cp)-[:USES_VIEWS {count: view_count}]->(dp)
            """)

            # 5. API dependencies: ExternalService → Endpoint discovery
            session.run("""
                MATCH (f:Function)-[:CALLS_EXTERNAL]->(s:ExternalService)
                WHERE size(s.display_name) >= 3
                MATCH (e:Endpoint)
                WHERE toLower(s.display_name) = toLower(e.handler_class)
                MERGE (f)-[:CALLS_API {target: e.route}]->(e)
            """)

            # 5b. URL→Endpoint matching is done per call-site in
            # WriterMixin._create_calls_api_from_urls. The previous node-level pass
            # (ExternalService.http_url) was removed: a shared service node carries a
            # single http_url, so it fanned one URL out to every caller (endpoint
            # collapse). Per-call-site matching preserves correct function identity.

            # 6. API dependencies between code projects
            session.run("""
                MATCH (f:Function)-[:CALLS_API]->(e:Endpoint)
                WHERE split(f.file, '/')[0] <> split(e.file, '/')[0]
                WITH split(f.file, '/')[0] AS consumer_proj,
                     split(e.file, '/')[0] AS provider_proj,
                     count(DISTINCT e.route) AS api_count
                MERGE (cp:Project {name: consumer_proj})
                MERGE (pp:Project {name: provider_proj})
                MERGE (cp)-[:CALLS_API {count: api_count}]->(pp)
            """)
