"""QueryMixin — all read-only query methods for CLI/MCP access."""

from __future__ import annotations

from neo4j import Session


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
                       x.file AS xfile, type(r) AS rel
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
                    })
            return {"entity": entity, "dependents": dependents, "total": len(dependents)}

    def query_schema(self) -> dict:
        """Return aggregated project structure from the graph."""
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
                "c.parent_class AS parent, c.interfaces AS ifaces"
            )
            for rec in cls_result:
                classes.append({
                    "name": rec["name"], "file": rec["file"],
                    "parent_class": rec["parent"], "interfaces": rec["ifaces"],
                })

            tables = []
            tbl_result = session.run(
                "MATCH (t:Table) RETURN t.name AS name, t.source_file AS src"
            )
            for rec in tbl_result:
                tables.append({"name": rec["name"], "source_file": rec["src"]})

            endpoints = []
            ep_result = session.run(
                "MATCH (e:Endpoint) RETURN e.http_method AS method, e.route AS path, "
                "e.handler_method AS handler, e.file AS file"
            )
            for rec in ep_result:
                endpoints.append({
                    "method": rec["method"], "path": rec["path"],
                    "handler": rec["handler"], "file": rec["file"],
                })

            services = []
            svc_result = session.run(
                "MATCH (es:ExternalService) RETURN es.display_name AS name, "
                "es.type AS type, es.source_file AS src"
            )
            for rec in svc_result:
                services.append({
                    "name": rec["name"], "type": rec["type"],
                    "source_file": rec["src"],
                })

            return {
                "stats": stats,
                "classes": classes,
                "tables": tables,
                "endpoints": endpoints,
                "external_services": services,
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
            return []

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

    def query_arch_summary(self) -> list[dict]:
        """Architecture summary: for each controller-like class, trace services, DAOs, tables, endpoints."""
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

            summaries = []
            for ctrl in controllers:
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

            return summaries

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
                           src.schema AS schema, src.file AS file, type(r) AS rel
                    LIMIT 100
                    """,
                    schema=obj["schema"], name=obj["name"],
                )
                for rec in down_result:
                    downstream.append({
                        "type": rec["type"], "name": rec["name"],
                        "schema": rec["schema"], "file": rec["file"],
                        "relation": rec["rel"],
                    })

            upstream = []
            if direction in ("upstream", "both"):
                up_result = session.run(
                    """
                    MATCH (src {schema: $schema, name: $name})-[r]->(target)
                    WHERE (target:Table OR target:View OR target:StoredProcedure OR target:DatabaseFunction)
                    RETURN labels(target)[0] AS type, target.name AS name,
                           target.schema AS schema, type(r) AS rel
                    LIMIT 100
                    """,
                    schema=obj["schema"], name=obj["name"],
                )
                for rec in up_result:
                    upstream.append({
                        "type": rec["type"], "name": rec["name"],
                        "schema": rec["schema"], "relation": rec["rel"],
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
                       length(path) AS depth
                ORDER BY depth, src.name
                LIMIT 200
                """,
                schema=obj["schema"], name=obj["name"],
            )
            for rec in imp_result:
                impacted.append({
                    "type": rec["type"], "name": rec["name"],
                    "schema": rec["schema"], "file": rec["file"],
                    "depth": rec["depth"],
                })

            return {"object": obj, "impacted": impacted}
