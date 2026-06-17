"""QueryMixin — all read-only query methods for CLI/MCP access."""

from __future__ import annotations

from neo4j import Session

# Pagination defaults for overview queries (keeps responses within MCP token limits).
DEFAULT_OVERVIEW_LIMIT = 100
MAX_OVERVIEW_LIMIT = 1000
# Architecture summaries are far heavier per item (services/DAOs/tables/endpoints
# per controller), so they default to a smaller page.
DEFAULT_ARCH_SUMMARY_LIMIT = 20

# select_files fallback tuning
SELECT_FILES_FALLBACK_LIMIT = 30
SELECT_FILES_MIN_TOKEN_LEN = 4


def _normalize_pagination(limit: int | None, offset: int | None) -> tuple[int, int]:
    """Clamp limit/offset to safe bounds."""
    if limit is None:
        limit = DEFAULT_OVERVIEW_LIMIT
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = DEFAULT_OVERVIEW_LIMIT
    if limit < 1:
        limit = DEFAULT_OVERVIEW_LIMIT
    if limit > MAX_OVERVIEW_LIMIT:
        limit = MAX_OVERVIEW_LIMIT
    try:
        offset = int(offset) if offset is not None else 0
    except (TypeError, ValueError):
        offset = 0
    if offset < 0:
        offset = 0
    return limit, offset


def _find_db_object(session: Session, object_name: str) -> dict | None:
    """Find DB object with priority: exact match > schema.name > CONTAINS."""
    # 1. Exact name match (prioritize dbo schema)
    result = session.run(
        """
        MATCH (obj)
        WHERE (obj:Table OR obj:View OR obj:StoredProcedure OR obj:DatabaseFunction)
        AND obj.name = $name
        RETURN labels(obj)[0] AS type, obj.schema AS schema, obj.name AS name
        ORDER BY CASE WHEN obj.schema = 'dbo' THEN 0 ELSE 1 END
        LIMIT 1
        """,
        name=object_name,
    )
    for rec in result:
        return {"type": rec["type"], "schema": rec["schema"], "name": rec["name"]}

    # 2. schema.name format
    if '.' in object_name:
        schema_part, name_part = object_name.split('.', 1)
        result = session.run(
            """
            MATCH (obj)
            WHERE (obj:Table OR obj:View OR obj:StoredProcedure OR obj:DatabaseFunction)
            AND obj.schema = $schema AND obj.name = $name
            RETURN labels(obj)[0] AS type, obj.schema AS schema, obj.name AS name
            LIMIT 1
            """,
            schema=schema_part, name=name_part,
        )
        for rec in result:
            return {"type": rec["type"], "schema": rec["schema"], "name": rec["name"]}

    # 3. Partial match (CONTAINS) — lowest priority
    result = session.run(
        """
        MATCH (obj)
        WHERE (obj:Table OR obj:View OR obj:StoredProcedure OR obj:DatabaseFunction)
        AND obj.name CONTAINS $name
        RETURN labels(obj)[0] AS type, obj.schema AS schema, obj.name AS name
        ORDER BY size(obj.name), obj.schema, obj.name
        LIMIT 1
        """,
        name=object_name,
    )
    for rec in result:
        return {"type": rec["type"], "schema": rec["schema"], "name": rec["name"]}

    return None


class QueryMixin:

    def query_call_chain(self, function_name: str, depth: int = 3) -> dict:
        """Return call chains starting from function_name up to depth levels."""
        with self.driver.session() as session:
            root_result = session.run(
                """
                MATCH (f:Function)
                WHERE f.name = $name OR f.name CONTAINS $name
                RETURN f.name AS name, f.file AS file, f.line AS line
                LIMIT 1
                """,
                name=function_name,
            )
            root = None
            for rec in root_result:
                root = {"name": rec["name"], "file": rec["file"], "line": rec["line"]}
            if root is None:
                return {"root": None, "chains": []}

            chain_query = (
                "MATCH (f:Function {name: $name}) "
                f"MATCH path = (f)-[:CALLS*1..{int(depth)}]->(g:Function) "
                "RETURN [node IN nodes(path) | "
                "{name: node.name, file: node.file, line: node.line}] AS chain "
                "LIMIT 50"
            )
            chain_result = session.run(chain_query, name=root["name"])
            chains = []
            for rec in chain_result:
                chain = rec["chain"]
                chains.append({
                    "path": [n["name"] for n in chain],
                    "files": [n["file"] for n in chain],
                })
            return {"root": root, "chains": chains}

    def query_impact(self, entity_name: str, entity_type: str = "auto") -> dict:
        """Return all entities that depend on the given entity."""
        type_queries = {
            "class": (
                "MATCH (c:Class) WHERE c.name = $name OR c.name CONTAINS $name",
                "Class",
                "c",
            ),
            "function": (
                "MATCH (f:Function) WHERE f.name = $name OR f.name CONTAINS $name",
                "Function",
                "f",
            ),
            "table": (
                "MATCH (t:Table) WHERE t.name = $name OR t.name CONTAINS $name",
                "Table",
                "t",
            ),
        }

        with self.driver.session() as session:
            entity = None
            matched_type = None

            types_to_check = (
                [entity_type] if entity_type in type_queries
                else ["class", "function", "table"]
            )
            for t in types_to_check:
                match_clause, label, var = type_queries[t]
                file_prop = "source_file" if t == "table" else "file"
                result = session.run(
                    f"{match_clause} RETURN {{name: {var}.name, "
                    f"file: {var}.{file_prop}, "
                    f"type: $label}} AS ent LIMIT 1",
                    name=entity_name, label=label,
                )
                for rec in result:
                    entity = rec["ent"]
                    matched_type = t
                if entity:
                    break

            if entity is None:
                return {"entity": None, "dependents": [], "total": 0}

            dep_result = session.run(
                f"""
                MATCH (src:{entity['type']}) WHERE src.name = $name
                MATCH (src)<-[r]-(x)
                RETURN labels(x)[0] AS xtype, x.name AS xname,
                       x.file AS xfile, type(r) AS rel,
                       r.confidence AS confidence, r.source AS source
                LIMIT 100
                """,
                name=entity["name"],
            )
            dependents = []
            seen = set()
            for rec in dep_result:
                key = (rec["xname"], rec["xtype"], rec["rel"])
                if key not in seen:
                    seen.add(key)
                    dependents.append({
                        "name": rec["xname"],
                        "type": rec["xtype"],
                        "file": rec["xfile"],
                        "relation": rec["rel"],
                        "confidence": rec["confidence"],
                        "source": rec["source"],
                    })
            return {"entity": entity, "dependents": dependents, "total": len(dependents)}

    def query_introspect(self, limit: int | None = None) -> dict:
        """Live schema introspection of the graph (labels, rel types, properties, shape).

        Lets the model learn what is actually in the graph before writing ad-hoc
        Cypher: every node label with its count and property names, every
        relationship type, and the observed (label)-[REL]->(label) connectivity
        patterns. The pattern list is capped (ordered by frequency) so the
        response stays within MCP token limits.
        """
        limit, _ = _normalize_pagination(limit, 0)
        with self.driver.session() as session:
            labels = session.run(
                "CALL db.labels() YIELD label RETURN label ORDER BY label"
            ).value()
            rel_types = session.run(
                "CALL db.relationshipTypes() YIELD relationshipType AS r "
                "RETURN r ORDER BY r"
            ).value()

            # Node counts per label (a node may carry several labels).
            node_counts = {}
            for rec in session.run(
                "MATCH (n) UNWIND labels(n) AS label "
                "RETURN label, count(*) AS c"
            ):
                node_counts[rec["label"]] = rec["c"]

            # Property names per label — metadata-driven; tolerate older servers.
            props: dict[str, set] = {}
            try:
                for rec in session.run(
                    "CALL db.schema.nodeTypeProperties() "
                    "YIELD nodeLabels, propertyName "
                    "RETURN nodeLabels, propertyName"
                ):
                    if not rec["propertyName"]:
                        continue
                    for lab in rec["nodeLabels"]:
                        props.setdefault(lab, set()).add(rec["propertyName"])
            except Exception:
                pass  # introspection procedure unavailable — return labels without props

            # Observed connectivity, ordered by frequency, capped to `limit`.
            patterns = []
            pat_result = session.run(
                "MATCH (a)-[r]->(b) "
                "WITH labels(a)[0] AS f, type(r) AS rel, labels(b)[0] AS t, count(*) AS c "
                "WHERE f IS NOT NULL AND t IS NOT NULL "
                "RETURN f, rel, t, c ORDER BY c DESC LIMIT $limit",
                limit=limit,
            )
            for rec in pat_result:
                patterns.append({
                    "from": rec["f"], "relationship": rec["rel"],
                    "to": rec["t"], "count": rec["c"],
                })

            label_info = [
                {
                    "label": lab,
                    "count": node_counts.get(lab, 0),
                    "properties": sorted(props.get(lab, [])),
                }
                for lab in labels
            ]

            return {
                "labels": label_info,
                "relationship_types": rel_types,
                "patterns": patterns,
                "pagination": {
                    "limit": limit,
                    "pattern_count": len(patterns),
                    "truncated": len(patterns) >= limit,
                },
            }

    def query_schema(self, limit: int | None = None, offset: int | None = None) -> dict:
        """Return aggregated project structure from the graph.

        Each entity list is paginated (SKIP/LIMIT) so the response stays within
        MCP token limits regardless of project size. Full counts are in `stats`;
        the `pagination` block reports the window and whether it was truncated.
        """
        limit, offset = _normalize_pagination(limit, offset)
        with self.driver.session() as session:
            stats_result = session.run(
                """
                MATCH (n)
                WHERE labels(n)[0] IN ['Class','Function','Table','Endpoint',
                    'ExternalService','ConfigEntry','ScheduledTask','FrameworkComponent']
                RETURN labels(n)[0] AS type, count(n) AS count
                ORDER BY count DESC
                """
            )
            stats = {rec["type"]: rec["count"] for rec in stats_result}

            classes = []
            cls_result = session.run(
                "MATCH (c:Class) RETURN c.name AS name, c.file AS file, "
                "c.parent_class AS parent, c.interfaces AS ifaces "
                "ORDER BY c.name SKIP $offset LIMIT $limit",
                offset=offset, limit=limit,
            )
            for rec in cls_result:
                classes.append({
                    "name": rec["name"], "file": rec["file"],
                    "parent_class": rec["parent"], "interfaces": rec["ifaces"],
                })

            tables = []
            tbl_result = session.run(
                "MATCH (t:Table) RETURN t.name AS name, t.source_file AS src "
                "ORDER BY t.name SKIP $offset LIMIT $limit",
                offset=offset, limit=limit,
            )
            for rec in tbl_result:
                tables.append({"name": rec["name"], "source_file": rec["src"]})

            endpoints = []
            ep_result = session.run(
                "MATCH (e:Endpoint) RETURN e.http_method AS method, e.route AS path, "
                "e.handler_method AS handler, e.file AS file "
                "ORDER BY e.route SKIP $offset LIMIT $limit",
                offset=offset, limit=limit,
            )
            for rec in ep_result:
                endpoints.append({
                    "method": rec["method"], "path": rec["path"],
                    "handler": rec["handler"], "file": rec["file"],
                })

            services = []
            svc_result = session.run(
                "MATCH (es:ExternalService) RETURN es.display_name AS name, "
                "es.type AS type, es.source_file AS src "
                "ORDER BY es.display_name SKIP $offset LIMIT $limit",
                offset=offset, limit=limit,
            )
            for rec in svc_result:
                services.append({
                    "name": rec["name"], "type": rec["type"],
                    "source_file": rec["src"],
                })

            totals = {
                "classes": stats.get("Class", 0),
                "tables": stats.get("Table", 0),
                "endpoints": stats.get("Endpoint", 0),
                "external_services": stats.get("ExternalService", 0),
            }
            truncated = any(total > offset + limit for total in totals.values())

            return {
                "stats": stats,
                "classes": classes,
                "tables": tables,
                "endpoints": endpoints,
                "external_services": services,
                "pagination": {
                    "limit": limit,
                    "offset": offset,
                    "totals": totals,
                    "truncated": truncated,
                },
            }

    def query_select_files(self, task_description: str) -> list[str]:
        """Select relevant files based on task description via keyword templates."""
        templates = {
            "архитектура": "MATCH (c:Class) RETURN DISTINCT c.file AS file",
            "C4": "MATCH (c:Class) RETURN DISTINCT c.file AS file",
            "компонент": "MATCH (c:Class) RETURN DISTINCT c.file AS file",
            "API": "MATCH (e:Endpoint) RETURN DISTINCT e.file AS file",
            "эндпоинт": "MATCH (e:Endpoint) RETURN DISTINCT e.file AS file",
            "роутинг": "MATCH (e:Endpoint) RETURN DISTINCT e.file AS file",
            "данн": "MATCH (t:Table)<-[:QUERIES]-(f:Function) RETURN DISTINCT f.file AS file",
            "таблиц": "MATCH (t:Table)<-[:QUERIES]-(f:Function) RETURN DISTINCT f.file AS file",
            "SQL": "MATCH (t:Table)<-[:QUERIES]-(f:Function) RETURN DISTINCT f.file AS file",
            "баз": "MATCH (t:Table)<-[:QUERIES]-(f:Function) RETURN DISTINCT f.file AS file",
            "вызов": "MATCH (f:Function)-[:CALLS]->(g:Function) RETURN DISTINCT f.file AS file",
            "цепочк": "MATCH (f:Function)-[:CALLS*1..3]->(g) RETURN DISTINCT f.file AS file",
            "data flow": "MATCH (f:Function)-[:CALLS*1..3]->(g) RETURN DISTINCT f.file AS file",
            "внешн": "MATCH (es:ExternalService)<-[:CALLS_EXTERNAL]-(f:Function) RETURN DISTINCT f.file AS file",
            "интеграц": "MATCH (es:ExternalService)<-[:CALLS_EXTERNAL]-(f:Function) RETURN DISTINCT f.file AS file",
            "конфигурац": "MATCH (c:ConfigEntry) RETURN DISTINCT c.file AS file",
            "настройк": "MATCH (c:ConfigEntry) RETURN DISTINCT c.file AS file",
            "cron": "MATCH (st:ScheduledTask) RETURN DISTINCT st.file AS file",
            "scheduled": "MATCH (st:ScheduledTask) RETURN DISTINCT st.file AS file",
            "фреймворк": "MATCH (fw:FrameworkComponent)<-[:USES_FRAMEWORK]-(f:Function) RETURN DISTINCT f.file AS file",
        }

        desc_lower = task_description.lower()
        matched_queries = set()
        for keyword, cypher in templates.items():
            if keyword.lower() in desc_lower:
                matched_queries.add(cypher)

        if not matched_queries:
            # Fallback: no dictionary keyword matched — rank files by how many
            # task tokens appear in entity names (Class/Function/Table/Endpoint).
            return self._select_files_fallback(task_description)

        files = set()
        with self.driver.session() as session:
            for cypher in matched_queries:
                result = session.run(cypher)
                for rec in result:
                    if rec["file"]:
                        files.add(rec["file"])

            if not files:
                return sorted(files)

            expand_result = session.run(
                """
                UNWIND $selected_files AS file
                MATCH (f:File {path: file})-[:DEFINES]->(n)
                MATCH (n)-[r]->(target)
                WHERE type(r) IN ['CALLS', 'QUERIES', 'EXTENDS', 'IMPORTS']
                  AND target.file IS NOT NULL
                RETURN DISTINCT target.file AS file
                """,
                selected_files=list(files),
            )
            for rec in expand_result:
                if rec["file"]:
                    files.add(rec["file"])

        return sorted(files)

    def _select_files_fallback(self, task_description: str) -> list[str]:
        """Rank files by how many task tokens appear in entity names.

        Used when no dictionary keyword matched. Matches description tokens
        (>= SELECT_FILES_MIN_TOKEN_LEN chars) against Class/Function/Table/Endpoint
        names, returning the files of matched nodes ranked by match count and
        capped at SELECT_FILES_FALLBACK_LIMIT.
        """
        import re

        raw_tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9_]+", task_description.lower())
        tokens = sorted({t for t in raw_tokens if len(t) >= SELECT_FILES_MIN_TOKEN_LEN})
        if not tokens:
            return []

        file_scores: dict[str, int] = {}
        with self.driver.session() as session:
            result = session.run(
                """
                UNWIND $tokens AS tok
                MATCH (n)
                WHERE (n:Class OR n:Function OR n:Table OR n:Endpoint)
                  AND n.name IS NOT NULL
                  AND toLower(n.name) CONTAINS tok
                WITH DISTINCT tok,
                     coalesce(n.file, n.source_file) AS file
                WHERE file IS NOT NULL
                RETURN file, count(DISTINCT tok) AS score
                ORDER BY score DESC, file
                LIMIT $limit
                """,
                tokens=tokens, limit=SELECT_FILES_FALLBACK_LIMIT,
            )
            for rec in result:
                file_scores[rec["file"]] = rec["score"]

        return sorted(file_scores, key=lambda f: (-file_scores[f], f))

    def query_export(self, entity_name: str = None, format: str = "text") -> str:
        """Export graph data as text, mermaid, or json."""
        if format == "json":
            import json
            if entity_name:
                impact = self.query_impact(entity_name)
                chains = self.query_call_chain(entity_name)
                return json.dumps({"impact": impact, "call_chain": chains}, ensure_ascii=False, indent=2)
            return json.dumps(self.query_schema(), ensure_ascii=False, indent=2)

        if format == "mermaid":
            return self._export_mermaid(entity_name)

        return self._export_text(entity_name)

    def _export_text(self, entity_name: str = None) -> str:
        """Human-readable text export."""
        lines = []
        schema = self.query_schema()
        stats = schema["stats"]
        lines.append("=== Project Structure ===")
        lines.append(" | ".join(f"{k}: {v}" for k, v in stats.items()))
        lines.append("")

        if entity_name:
            impact = self.query_impact(entity_name)
            chains = self.query_call_chain(entity_name)
            if impact["entity"]:
                ent = impact["entity"]
                lines.append(f"--- Entity: {ent['name']} ({ent['type']}) ---")
                if ent.get("file"):
                    lines.append(f"File: {ent['file']}")
                if impact["dependents"]:
                    lines.append(f"Dependents ({impact['total']}):")
                    for d in impact["dependents"]:
                        lines.append(f"  - {d['name']} ({d['type']}) [{d['relation']}] in {d['file']}")
                if chains["chains"]:
                    lines.append("Call chains:")
                    for ch in chains["chains"]:
                        lines.append(f"  {' -> '.join(ch['path'])}")
            else:
                lines.append(f"Entity '{entity_name}' not found in graph.")
            return "\n".join(lines)

        for cls in schema["classes"]:
            parts = [f"--- Class: {cls['name']} ({cls['file']}) ---"]
            if cls.get("parent_class"):
                parts.append(f"Parent: {cls['parent_class']}")
            lines.append("\n".join(parts))

        for ep in schema["endpoints"]:
            lines.append(f"--- Endpoint: {ep.get('method', '?')} {ep.get('path', '?')} ---")
            if ep.get("handler"):
                lines.append(f"Handler: {ep['handler']} ({ep['file']})")

        for t in schema["tables"]:
            lines.append(f"--- Table: {t['name']} ---")

        for svc in schema["external_services"]:
            lines.append(f"--- External: {svc['name']} ({svc.get('type', '?')}) ---")

        return "\n".join(lines)

    def _export_mermaid(self, entity_name: str = None) -> str:
        """Mermaid graph export."""
        lines = ["graph LR"]
        with self.driver.session() as session:
            if entity_name:
                result = session.run(
                    """
                    MATCH (f:Function)
                    WHERE f.name = $name OR f.name CONTAINS $name
                    OPTIONAL MATCH path = (f)-[:CALLS*1..3]->(g)
                    RETURN [node IN nodes(path) |
                        {name: node.name, file: node.file}] AS chain
                    LIMIT 30
                    """,
                    name=entity_name,
                )
                seen = set()
                for rec in result:
                    chain = rec["chain"]
                    for i in range(len(chain) - 1):
                        src = chain[i]["name"].replace('"', "'")
                        dst = chain[i + 1]["name"].replace('"', "'")
                        key = (src, dst)
                        if key not in seen:
                            seen.add(key)
                            lines.append(f'    {src}["{src}"] --> {dst}["{dst}"]')
            else:
                result = session.run(
                    """
                    MATCH (c:Class)
                    RETURN c.name AS name LIMIT 30
                    """
                )
                for rec in result:
                    name = rec["name"].replace('"', "'")
                    lines.append(f'    {name}["{name}"]')

                rel_result = session.run(
                    """
                    MATCH (a:Class)-[r:EXTENDS|IMPLEMENTS]->(b:Class)
                    RETURN a.name AS src, type(r) AS rel, b.name AS dst
                    LIMIT 30
                    """
                )
                for rec in rel_result:
                    src = rec["src"].replace('"', "'")
                    dst = rec["dst"].replace('"', "'")
                    lines.append(f'    {src} -->|{rec["rel"]}| {dst}')

        if len(lines) == 1:
            lines.append("    Empty[Graph is empty]")
        return "\n".join(lines)

    def query_arch_summary(self, limit: int | None = None, offset: int | None = None) -> dict:
        """Architecture summary: for each controller-like class, trace services, DAOs, tables, endpoints.

        Paginated over the controller list so the response stays within MCP token
        limits; only the requested window of controllers is traced. Returns a dict
        with `summaries` and a `pagination` block (total controllers + truncation).
        """
        if limit is None:
            limit = DEFAULT_ARCH_SUMMARY_LIMIT
        limit, offset = _normalize_pagination(limit, offset)
        with self.driver.session() as session:
            controllers_result = session.run(
                """
                MATCH (c:Class)
                WHERE c.name CONTAINS 'Controller'
                   OR EXISTS {
                     MATCH (c)-[:HAS_METHOD]->(f:Function {is_entry_point: true})
                   }
                   OR EXISTS {
                     MATCH (e:Endpoint)-[:DEFINED_IN]->(c)
                   }
                RETURN c.name AS name, c.file AS file
                ORDER BY c.name
                """
            )
            controllers = []
            for rec in controllers_result:
                controllers.append({"name": rec["name"], "file": rec["file"]})

            if not controllers:
                all_classes_result = session.run(
                    "MATCH (c:Class) RETURN c.name AS name, c.file AS file ORDER BY c.name"
                )
                for rec in all_classes_result:
                    controllers.append({"name": rec["name"], "file": rec["file"]})

            total_controllers = len(controllers)
            page = controllers[offset:offset + limit]

            summaries = []
            for ctrl in page:
                ctrl_name = ctrl["name"]

                svc_result = session.run(
                    """
                    MATCH (c:Class {name: $name})-[:HAS_METHOD]->(mf:Function)
                    MATCH (mf)-[:CALLS]->(sf:Function)
                    WHERE sf.class_name IS NOT NULL AND sf.class_name <> $name
                    RETURN DISTINCT sf.class_name AS service_class
                    ORDER BY service_class
                    """,
                    name=ctrl_name,
                )
                services = [rec["service_class"] for rec in svc_result]

                tbl_result = session.run(
                    """
                    MATCH (c:Class {name: $name})-[:HAS_METHOD]->(mf:Function)
                    MATCH (mf)-[:CALLS*1..3]->(intermediate:Function)
                    MATCH (intermediate)-[:QUERIES]->(t:Table)
                    RETURN DISTINCT t.name AS table_name
                    ORDER BY table_name
                    """,
                    name=ctrl_name,
                )
                tables = [rec["table_name"] for rec in tbl_result]

                ext_result = session.run(
                    """
                    MATCH (c:Class {name: $name})-[:HAS_METHOD]->(mf:Function)
                    MATCH (mf)-[:CALLS*1..3]->(intermediate:Function)
                    MATCH (intermediate)-[:CALLS_EXTERNAL]->(es:ExternalService)
                    RETURN DISTINCT es.display_name AS ext_name
                    ORDER BY ext_name
                    """,
                    name=ctrl_name,
                )
                external = [rec["ext_name"] for rec in ext_result if rec["ext_name"]]

                ep_result = session.run(
                    """
                    MATCH (e:Endpoint)-[:DEFINED_IN]->(c:Class {name: $name})
                    RETURN e.http_method AS method, e.route AS path
                    ORDER BY e.route
                    """,
                    name=ctrl_name,
                )
                endpoints = [
                    f"{rec['method'] or '?'} {rec['path'] or '?'}" for rec in ep_result
                ]

                dao_result = session.run(
                    """
                    MATCH (c:Class {name: $name})-[:HAS_METHOD]->(mf:Function)
                    MATCH (mf)-[:CALLS*1..3]->(dao_func:Function)
                    WHERE dao_func.class_name IS NOT NULL AND dao_func.class_name <> $name
                    MATCH (dao_func)-[:QUERIES]->(:Table)
                    RETURN DISTINCT dao_func.class_name AS dao_class
                    ORDER BY dao_class
                    """,
                    name=ctrl_name,
                )
                daos = [rec["dao_class"] for rec in dao_result]

                summaries.append({
                    "controller": ctrl_name,
                    "file": ctrl["file"],
                    "services": services,
                    "daos": daos,
                    "tables": tables,
                    "external_services": external,
                    "endpoints": endpoints,
                })

            return {
                "summaries": summaries,
                "pagination": {
                    "limit": limit,
                    "offset": offset,
                    "total": total_controllers,
                    "truncated": total_controllers > offset + limit,
                },
            }

    def query_db_schema(self, schema_name: str | None = None) -> dict:
        """Return all DB objects with types, schemas, columns."""
        schema_filter = ""
        params = {}
        if schema_name:
            schema_filter = " AND obj.schema = $schema"
            params["schema"] = schema_name

        with self.driver.session() as session:
            objects = []
            result = session.run(
                f"""
                MATCH (obj)
                WHERE (obj:Table OR obj:View OR obj:StoredProcedure OR obj:DatabaseFunction)
                {schema_filter}
                RETURN labels(obj)[0] AS type, obj.schema AS schema, obj.name AS name,
                       obj.source_file AS source_file, obj.source_line AS source_line,
                       obj.columns AS columns, obj.parameters AS parameters,
                       obj.return_type AS return_type, obj.body_sql AS body_sql
                ORDER BY obj.schema, labels(obj)[0], obj.name
                """,
                **params,
            )
            for rec in result:
                obj = {
                    "type": rec["type"],
                    "schema": rec["schema"],
                    "name": rec["name"],
                    "source_file": rec["source_file"],
                }
                if rec["columns"]:
                    obj["columns"] = rec["columns"]
                if rec["parameters"]:
                    obj["parameters"] = rec["parameters"]
                if rec["return_type"]:
                    obj["return_type"] = rec["return_type"]
                if rec["body_sql"]:
                    obj["body_sql"] = rec["body_sql"][:500]
                objects.append(obj)
            return {"objects": objects, "count": len(objects)}

    def query_db_lineage(self, object_name: str, direction: str = "both") -> dict:
        """Upstream and downstream lineage for a DB object."""
        with self.driver.session() as session:
            obj = _find_db_object(session, object_name)
            if not obj:
                return {"object": None, "upstream": [], "downstream": []}

            downstream = []
            if direction in ("downstream", "both"):
                down_result = session.run(
                    """
                    MATCH (src)-[r]->(target)
                    WHERE (src:View OR src:StoredProcedure OR src:DatabaseFunction OR src:Function)
                      AND (target:Table OR target:View OR target:StoredProcedure OR target:DatabaseFunction)
                      AND target.schema = $schema AND target.name = $name
                    RETURN labels(src)[0] AS type, src.name AS name,
                           src.schema AS schema, src.file AS file, type(r) AS rel,
                           r.confidence AS confidence, r.source AS source
                    LIMIT 100
                    """,
                    schema=obj["schema"], name=obj["name"],
                )
                for rec in down_result:
                    downstream.append({
                        "type": rec["type"], "name": rec["name"],
                        "schema": rec["schema"], "file": rec["file"],
                        "relation": rec["rel"],
                        "confidence": rec["confidence"], "source": rec["source"],
                    })

            upstream = []
            if direction in ("upstream", "both"):
                up_result = session.run(
                    """
                    MATCH (src {schema: $schema, name: $name})-[r]->(target)
                    WHERE (target:Table OR target:View OR target:StoredProcedure OR target:DatabaseFunction)
                    RETURN labels(target)[0] AS type, target.name AS name,
                           target.schema AS schema, type(r) AS rel,
                           r.confidence AS confidence, r.source AS source
                    LIMIT 100
                    """,
                    schema=obj["schema"], name=obj["name"],
                )
                for rec in up_result:
                    upstream.append({
                        "type": rec["type"], "name": rec["name"],
                        "schema": rec["schema"], "relation": rec["rel"],
                        "confidence": rec["confidence"], "source": rec["source"],
                    })

            return {"object": obj, "upstream": upstream, "downstream": downstream}

    def query_db_orphans(self) -> list[dict]:
        """DB objects with no connections at all — unused tables, views, stored procedures."""
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (obj)
                WHERE (obj:Table OR obj:View OR obj:StoredProcedure OR obj:DatabaseFunction)
                AND obj.schema IS NOT NULL
                AND NOT (obj)--()
                RETURN labels(obj)[0] AS type, obj.schema AS schema, obj.name AS name,
                       obj.source_file AS source_file
                ORDER BY obj.schema, obj.name
                """
            )
            return [
                {"type": rec["type"], "schema": rec["schema"], "name": rec["name"],
                 "source_file": rec["source_file"]}
                for rec in result
            ]

    def query_db_unresolved(self) -> list[dict]:
        """Table/SP references in code not found in DDL nodes."""
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (f:Function)-[r:QUERIES|CALLS_SP]->(ref)
                WHERE (ref:Table OR ref:StoredProcedure)
                AND NOT EXISTS {
                    MATCH (ddl)
                    WHERE (ddl:Table OR ddl:View OR ddl:StoredProcedure OR ddl:DatabaseFunction)
                    AND ddl.schema = ref.schema AND ddl.name = ref.name
                }
                RETURN DISTINCT ref.schema AS schema, ref.name AS name,
                       labels(ref)[0] AS ref_type, type(r) AS rel,
                       f.name AS function_name, f.file AS file
                ORDER BY ref.name
                LIMIT 200
                """
            )
            return [
                {"schema": rec["schema"], "name": rec["name"],
                 "ref_type": rec["ref_type"], "relation": rec["rel"],
                 "function": rec["function_name"], "file": rec["file"]}
                for rec in result
            ]

    def query_db_impact(self, object_name: str) -> dict:
        """Transitive impact analysis for a DB object through the DB graph."""
        with self.driver.session() as session:
            obj = _find_db_object(session, object_name)
            if not obj:
                return {"object": None, "impacted": []}

            impacted = []
            imp_result = session.run(
                """
                MATCH path = (src)-[:QUERIES|CALLS_SP|INSERTS_INTO|UPDATES|DELETES_FROM|DEPENDS_ON*1..3]->(target {schema: $schema, name: $name})
                RETURN DISTINCT labels(src)[0] AS type, src.name AS name,
                       src.schema AS schema, src.file AS file,
                       length(path) AS depth,
                       [rel IN relationships(path) | rel.confidence] AS confidences,
                       [rel IN relationships(path) | rel.source] AS sources
                ORDER BY depth, src.name
                LIMIT 200
                """,
                schema=obj["schema"], name=obj["name"],
            )
            # Path confidence is the weakest edge along the path; inferred if any
            # edge on the path came from the inventory resolver.
            _rank = {"low": 0, "medium": 1, "high": 2}
            for rec in imp_result:
                confs = [c for c in (rec["confidences"] or []) if c]
                path_conf = min(confs, key=lambda c: _rank.get(c, 3)) if confs else None
                srcs = [s for s in (rec["sources"] or []) if s]
                path_source = "inventory_resolver" if "inventory_resolver" in srcs else (
                    srcs[0] if srcs else None)
                impacted.append({
                    "type": rec["type"], "name": rec["name"],
                    "schema": rec["schema"], "file": rec["file"],
                    "depth": rec["depth"],
                    "confidence": path_conf, "source": path_source,
                })

            return {"object": obj, "impacted": impacted}
