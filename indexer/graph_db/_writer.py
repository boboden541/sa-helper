"""WriterMixin — node creation methods (create_*)."""

from __future__ import annotations

from graph_db._base import _url_match_score


class WriterMixin:

    def create_project(self, name: str, path: str, total_files: int, total_lines: int,
                       project_type: str = "code"):
        with self.driver.session() as session:
            session.run(
                """
                MERGE (p:Project {name: $name})
                SET p.path = $path,
                    p.total_files = $total_files,
                    p.total_lines = $total_lines,
                    p.type = $project_type,
                    p.indexed_at = datetime()
                """,
                name=name, path=path,
                total_files=total_files, total_lines=total_lines,
                project_type=project_type,
            )

    def create_file_tree(self, files: list[dict]):
        dirs = set()
        dir_parents = []
        dir_files = []
        for f in files:
            parts = f["rel_path"].split("/")[:-1]
            for i in range(len(parts)):
                dir_path = "/".join(parts[: i + 1]) + "/"
                dirs.add(dir_path)
                parent_path = "/".join(parts[:i]) + "/" if i > 0 else None
                if parent_path:
                    dir_parents.append((parent_path, dir_path))

            dir_path = "/".join(parts) + "/" if parts else None
            if dir_path:
                dir_files.append((dir_path, f["rel_path"]))

        with self.driver.session() as session:
            for chunk in self._chunks(files):
                session.run(
                    """
                    UNWIND $files AS f
                    MERGE (file:File {path: f.rel_path})
                    SET file.language = f.language,
                        file.lines = f.lines,
                        file.bytes = f.bytes
                    """,
                    files=chunk,
                )

            for chunk in self._chunks(list(dirs)):
                session.run(
                    """
                    UNWIND $dirs AS d
                    MERGE (dir:Directory {path: d})
                    """,
                    dirs=chunk,
                )

            for chunk in self._chunks(dir_parents):
                session.run(
                    """
                    UNWIND $pairs AS p
                    MATCH (parent:Directory {path: p[0]})
                    MATCH (child:Directory {path: p[1]})
                    MERGE (parent)-[:CONTAINS]->(child)
                    """,
                    pairs=chunk,
                )

            for chunk in self._chunks(dir_files):
                session.run(
                    """
                    UNWIND $pairs AS p
                    MATCH (d:Directory {path: p[0]})
                    MATCH (f:File {path: p[1]})
                    MERGE (d)-[:CONTAINS]->(f)
                    """,
                    pairs=chunk,
                )

    def create_classes(self, classes: list[dict]):
        if not classes:
            return
        with self.driver.session() as session:
            for chunk in self._chunks(classes):
                session.run(
                    """
                    UNWIND $classes AS c
                    MERGE (cls:Class {name: c.name, file: c.file, line: c.line})
                    SET cls.parent_class = c.parent_class,
                        cls.interfaces = c.interfaces
                    WITH cls, c
                    MATCH (f:File {path: c.file})
                    MERGE (f)-[:DEFINES]->(cls)
                    """,
                    classes=chunk,
                )

    def create_inheritance(self):
        with self.driver.session() as session:
            session.run(
                """
                MATCH (child:Class)
                WHERE child.parent_class IS NOT NULL
                MATCH (parent:Class {name: child.parent_class})
                MERGE (child)-[:EXTENDS]->(parent)
                """
            )
            session.run(
                """
                MATCH (cls:Class)
                WHERE cls.interfaces IS NOT NULL AND size(cls.interfaces) > 0
                UNWIND cls.interfaces AS iface_name
                MATCH (iface:Class {name: iface_name})
                MERGE (cls)-[:IMPLEMENTS]->(iface)
                """
            )

    def create_external_references(self):
        with self.driver.session() as session:
            session.run(
                """
                MATCH (child:Class)
                WHERE child.parent_class IS NOT NULL
                AND NOT EXISTS {
                    MATCH (parent:Class {name: child.parent_class})
                }
                MERGE (ext:ExternalClass {name: child.parent_class})
                MERGE (child)-[:EXTENDS]->(ext)
                """
            )
            session.run(
                """
                MATCH (cls:Class)
                WHERE cls.interfaces IS NOT NULL AND size(cls.interfaces) > 0
                UNWIND cls.interfaces AS iface_name
                WITH cls, iface_name
                WHERE NOT EXISTS {
                    MATCH (iface:Class {name: iface_name})
                }
                MERGE (ext:ExternalClass {name: iface_name})
                MERGE (cls)-[:IMPLEMENTS]->(ext)
                """
            )

    def create_functions(self, functions: list[dict]):
        if not functions:
            return
        with self.driver.session() as session:
            for chunk in self._chunks(functions):
                session.run(
                    """
                    UNWIND $funcs AS fn
                    MERGE (func:Function {name: fn.name, file: fn.file, line: fn.line})
                    SET func.parameters = fn.parameters,
                        func.is_method = fn.is_method,
                        func.class_name = fn.class_name,
                        func.is_entry_point = fn.is_entry_point
                    WITH func, fn
                    MATCH (f:File {path: fn.file})
                    MERGE (f)-[:DEFINES]->(func)
                    """,
                    funcs=chunk,
                )
                session.run(
                    """
                    UNWIND $funcs AS fn
                    WITH fn
                    WHERE fn.class_name IS NOT NULL
                    MATCH (cls:Class {name: fn.class_name, file: fn.file})
                    MATCH (func:Function {name: fn.name, file: fn.file, line: fn.line})
                    MERGE (cls)-[:HAS_METHOD]->(func)
                    """,
                    funcs=chunk,
                )

    def create_imports(self, imports: list[dict]):
        if not imports:
            return
        with self.driver.session() as session:
            for chunk in self._chunks(imports):
                session.run(
                    """
                    UNWIND $imports AS imp
                    MERGE (i:Import {source: imp.source, file: imp.file})
                    SET i.aliases = imp.aliases
                    WITH i, imp
                    MATCH (f:File {path: imp.file})
                    MERGE (f)-[:IMPORTS]->(i)
                    """,
                    imports=chunk,
                )

    def resolve_imports(self):
        """Multi-level import resolving: path-based > short name > alias."""
        with self.driver.session() as session:
            session.run(
                """
                MATCH (i:Import)
                WITH i, split(i.source, '\\\\')[-1] AS short_name,
                     replace(replace(i.source, '\\\\', '/'), '//', '/') AS path_candidate
                OPTIONAL MATCH (c1:Class {name: short_name})
                OPTIONAL MATCH (c2:Class) WHERE c2.file CONTAINS path_candidate
                WITH i, COALESCE(c1, c2) AS resolved
                WHERE resolved IS NOT NULL
                MERGE (i)-[:RESOLVES_TO]->(resolved)
                """
            )
            session.run(
                """
                MATCH (i:Import)
                WHERE i.aliases IS NOT NULL AND size(i.aliases) > 0
                AND NOT (i)-[:RESOLVES_TO]->(:Class)
                UNWIND i.aliases AS alias
                MATCH (c:Class {name: alias})
                MERGE (i)-[:RESOLVES_TO]->(c)
                """
            )

    def create_calls(self, calls: list[dict]):
        if not calls:
            return
        with self.driver.session() as session:
            for chunk in self._chunks(calls):
                session.run(
                    """
                    UNWIND $calls AS call
                    WITH call WHERE size(call.callee_name) >= 2
                    MERGE (caller:Function {name: call.caller_name, file: call.caller_file, line: call.caller_line})
                    WITH caller, call
                    MATCH (callee:Function {name: call.callee_name})
                    WHERE callee.file IS NOT NULL
                    AND (call.callee_file IS NULL OR callee.file = call.callee_file)
                    MERGE (caller)-[:CALLS]->(callee)
                    """,
                    calls=chunk,
                )

    def create_tables(self, tables: list[dict], default_schema: str | None = None):
        if not tables:
            return
        import json as _json
        for t in tables:
            if t.get("columns") and isinstance(t["columns"], list):
                t["columns"] = _json.dumps(t["columns"], ensure_ascii=False)
            if not t.get("schema"):
                t["schema"] = default_schema
        with self.driver.session() as session:
            for chunk in self._chunks(tables):
                # Create Table nodes only when no View with same (schema, name) exists
                session.run(
                    """
                    UNWIND $tables AS t
                    WITH t WHERE t.type = 'table'
                    OPTIONAL MATCH (existing_view:View {schema: t.schema, name: t.name})
                    FOREACH (_ IN CASE WHEN existing_view IS NULL THEN [1] ELSE [] END |
                        MERGE (tbl:Table {schema: t.schema, name: t.name})
                        SET tbl.source_file = t.source_file,
                            tbl.source_line = t.source_line,
                            tbl.columns = t.columns
                    )
                    FOREACH (_ IN CASE WHEN existing_view IS NOT NULL THEN [1] ELSE [] END |
                        SET existing_view.source_file = CASE
                            WHEN existing_view.source_file IS NULL THEN t.source_file
                            ELSE existing_view.source_file
                        END
                    )
                    """,
                    tables=chunk,
                )
                # Link Function to View (priority) or Table
                session.run(
                    """
                    UNWIND $tables AS t
                    WITH t WHERE t.type = 'table' AND t.function_name IS NOT NULL
                    MATCH (f:Function {name: t.function_name})
                    WHERE f.file = t.file
                    OPTIONAL MATCH (v:View {schema: t.schema, name: t.name})
                    OPTIONAL MATCH (tbl:Table {schema: t.schema, name: t.name})
                    WITH t, f, v, tbl
                    WHERE v IS NOT NULL OR tbl IS NOT NULL
                    FOREACH (_ IN CASE WHEN v IS NOT NULL THEN [1] ELSE [] END |
                        MERGE (f)-[:QUERIES]->(v)
                    )
                    FOREACH (_ IN CASE WHEN v IS NULL AND tbl IS NOT NULL THEN [1] ELSE [] END |
                        MERGE (f)-[:QUERIES]->(tbl)
                    )
                    """,
                    tables=chunk,
                )
                session.run(
                    """
                    UNWIND $tables AS t
                    WITH t WHERE t.type = 'stored_procedure'
                      AND t.source_file ENDS WITH '.sql'
                    MERGE (sp:StoredProcedure {schema: t.schema, name: t.name})
                    SET sp.source_file = t.source_file,
                        sp.source_line = t.source_line
                    """,
                    tables=chunk,
                )
                session.run(
                    """
                    UNWIND $tables AS t
                    WITH t WHERE t.type = 'stored_procedure' AND t.function_name IS NOT NULL
                    MATCH (sp:StoredProcedure {schema: t.schema, name: t.name})
                    MATCH (f:Function {name: t.function_name})
                    WHERE f.file = t.file
                    MERGE (f)-[:CALLS_SP]->(sp)
                    """,
                    tables=chunk,
                )

    def create_endpoints(self, endpoints: list[dict]):
        if not endpoints:
            return
        with self.driver.session() as session:
            for chunk in self._chunks(endpoints):
                session.run(
                    """
                    UNWIND $endpoints AS ep
                    MERGE (e:Endpoint {name: ep.name, type: ep.type})
                    SET e.handler_method = ep.handler_method,
                        e.handler_class = ep.handler_class,
                        e.route = ep.route,
                        e.file = ep.file,
                        e.line = ep.line,
                        e.http_method = ep.http_method
                    WITH e, ep
                    MATCH (f:File {path: ep.file})
                    MERGE (f)-[:DEFINES]->(e)
                    """,
                    endpoints=chunk,
                )
                session.run(
                    """
                    UNWIND $endpoints AS ep
                    MATCH (e:Endpoint {name: ep.name, type: ep.type})
                    MATCH (func:Function {name: ep.handler_method, file: ep.file})
                    MERGE (e)-[:HANDLED_BY]->(func)
                    """,
                    endpoints=chunk,
                )
                session.run(
                    """
                    UNWIND $endpoints AS ep
                    WITH ep
                    WHERE ep.handler_class IS NOT NULL
                    MATCH (e:Endpoint {name: ep.name, type: ep.type})
                    MATCH (c:Class {name: ep.handler_class, file: ep.file})
                    MERGE (e)-[:DEFINED_IN]->(c)
                    """,
                    endpoints=chunk,
                )

    def create_external_services(self, services: list[dict]):
        if not services:
            return
        with self.driver.session() as session:
            for chunk in self._chunks(services):
                session.run(
                    """
                    UNWIND $services AS svc
                    WITH svc WHERE svc.service_class IS NOT NULL
                    MATCH (c:Class) WHERE toLower(c.name) = toLower(svc.service_class)
                    MATCH (f:Function {name: svc.function_name, file: svc.file})
                    WHERE f.class_name IS NULL OR toLower(f.class_name) <> toLower(c.name)
                    MERGE (f)-[:DEPENDS_ON]->(c)
                    """,
                    services=chunk,
                )
                session.run(
                    """
                    UNWIND $services AS svc
                    WITH svc WHERE svc.service_class IS NOT NULL
                    AND NOT EXISTS {
                        MATCH (c:Class) WHERE toLower(c.name) = toLower(svc.service_class)
                    }
                    MERGE (s:ExternalService {name: toLower(svc.service_class)})
                    SET s.display_name = svc.service_class, s.type = 'external_client',
                        s.source_file = svc.file,
                        s.http_url = svc.http_url
                    WITH s, svc
                    MATCH (f:Function {name: svc.function_name, file: svc.file})
                    MERGE (f)-[:CALLS_EXTERNAL {method: svc.method}]->(s)
                    """,
                    services=chunk,
                )
                session.run(
                    """
                    UNWIND $services AS svc
                    WITH svc WHERE svc.service_var IS NOT NULL AND svc.service_class IS NULL
                    MATCH (c:Class) WHERE toLower(c.name) = toLower(svc.service_var)
                    MATCH (f:Function {name: svc.function_name, file: svc.file})
                    WHERE f.class_name IS NULL OR toLower(f.class_name) <> toLower(c.name)
                    MERGE (f)-[:DEPENDS_ON]->(c)
                    """,
                    services=chunk,
                )
                session.run(
                    """
                    UNWIND $services AS svc
                    WITH svc WHERE svc.service_var IS NOT NULL AND svc.service_class IS NULL
                    AND NOT EXISTS {
                        MATCH (c:Class) WHERE toLower(c.name) = toLower(svc.service_var)
                    }
                    MERGE (s:ExternalService {name: toLower(svc.service_var)})
                    SET s.display_name = svc.service_var, s.type = 'external_instance',
                        s.source_file = svc.file,
                        s.http_url = svc.http_url
                    WITH s, svc
                    MATCH (f:Function {name: svc.function_name, file: svc.file})
                    MERGE (f)-[:CALLS_EXTERNAL {method: svc.method}]->(s)
                    """,
                    services=chunk,
                )
            # URL-based CALLS_API matching via Python normalization
            self._create_calls_api_from_urls(services)

    def _create_calls_api_from_urls(self, services: list[dict]):
        """Create CALLS_API relationships by matching frontend URLs to backend endpoints."""
        url_services = [s for s in services if s.get("http_url") and s.get("http_method")]
        if not url_services:
            return

        with self.driver.session() as session:
            result = session.run(
                "MATCH (e:Endpoint) RETURN e.route AS route, e.file AS file"
            )
            endpoints = [dict(record) for record in result]

        matches = []
        for svc in url_services:
            # Pick the most specific endpoint (most matched segments), not the first
            # match — suffix matching otherwise collapses unrelated short routes.
            best = None
            best_score = -1
            for ep in endpoints:
                if not ep["route"]:
                    continue
                score = _url_match_score(svc["http_url"], ep["route"])
                if score is None:
                    continue
                # Deterministic tie-break by route for stable output.
                if score > best_score or (score == best_score and best is not None
                                          and ep["route"] < best["route"]):
                    best = ep
                    best_score = score
            if best is not None:
                matches.append({
                    "function_name": svc["function_name"],
                    "file": svc["file"],
                    "http_method": svc["http_method"],
                    "http_url": svc["http_url"],
                    "endpoint_route": best["route"],
                    "endpoint_file": best["file"],
                })

        if not matches:
            return

        with self.driver.session() as session:
            for chunk in self._chunks(matches):
                session.run(
                    """
                    UNWIND $matches AS m
                    MATCH (f:Function {name: m.function_name, file: m.file})
                    MATCH (e:Endpoint {route: m.endpoint_route})
                    WHERE e.file = m.endpoint_file OR m.endpoint_file IS NULL
                    MERGE (f)-[:CALLS_API {http_method: m.http_method, url: m.http_url}]->(e)
                    """,
                    matches=chunk,
                )

    def create_framework_usage(self, usage: list[dict]):
        if not usage:
            return
        with self.driver.session() as session:
            for chunk in self._chunks(usage):
                session.run(
                    """
                    UNWIND $usage AS u
                    MERGE (fw:FrameworkComponent {name: u.name, framework: u.framework, type: u.type})
                    SET fw.pattern = u.pattern,
                        fw.source_file = u.file
                    WITH fw, u
                    MATCH (f:Function {name: u.function_name, file: u.file})
                    MERGE (f)-[:USES_FRAMEWORK]->(fw)
                    """,
                    usage=chunk,
                )

    def create_scheduled_tasks(self, tasks: list[dict]):
        if not tasks:
            return
        with self.driver.session() as session:
            for chunk in self._chunks(tasks):
                session.run(
                    """
                    UNWIND $tasks AS t
                    MERGE (st:ScheduledTask {name: t.name, file: t.file, line: t.line})
                    SET st.schedule = t.schedule,
                        st.command = t.command,
                        st.type = t.type
                    """,
                    tasks=chunk,
                )
                session.run(
                    """
                    UNWIND $tasks AS t
                    MATCH (st:ScheduledTask {name: t.name, file: t.file, line: t.line})
                    MATCH (f:File {path: t.file})
                    MERGE (f)-[:DEFINES]->(st)
                    """,
                    tasks=chunk,
                )

    def create_config_entries(self, entries: list[dict]):
        if not entries:
            return
        with self.driver.session() as session:
            for chunk in self._chunks(entries):
                session.run(
                    """
                    UNWIND $entries AS e
                    MERGE (ce:ConfigEntry {key: e.key, file: e.file})
                    SET ce.value = e.value,
                        ce.type = e.type,
                        ce.line = e.line,
                        ce.source_file = e.file
                    """,
                    entries=chunk,
                )
                session.run(
                    """
                    UNWIND $entries AS e
                    MATCH (ce:ConfigEntry {key: e.key, file: e.file})
                    MATCH (f:File {path: e.file})
                    MERGE (f)-[:DEFINES]->(ce)
                    """,
                    entries=chunk,
                )

    def create_db_objects(self, objects: list[dict], default_schema: str | None = None):
        """Create View/StoredProcedure/DatabaseFunction nodes from DDL + their dependencies."""
        if not objects:
            return
        import json as _json
        for o in objects:
            if not o.get("schema"):
                o["schema"] = default_schema
            for dep in o.get("dependencies", []):
                if not dep.get("target_schema"):
                    dep["target_schema"] = default_schema
        views = [o for o in objects if o["label"] == "View"]
        procs = [o for o in objects if o["label"] == "StoredProcedure"]
        funcs = [o for o in objects if o["label"] == "DatabaseFunction"]

        def _ser(obj, keys):
            out = dict(obj)
            for k in keys:
                v = out.get(k)
                if v and isinstance(v, (list, dict)):
                    out[k] = _json.dumps(v, ensure_ascii=False)
            return out

        views = [_ser(v, ["body_sql"]) for v in views]
        procs = [_ser(p, ["parameters"]) for p in procs]
        funcs = [_ser(f, ["parameters", "return_type"]) for f in funcs]

        with self.driver.session() as session:
            for chunk in self._chunks(views):
                session.run(
                    """
                    UNWIND $views AS v
                    MERGE (view:View {schema: v.schema, name: v.name})
                    SET view.body_sql = v.body_sql,
                        view.source_file = v.source_file,
                        view.source_line = v.source_line
                    """,
                    views=chunk,
                )
                session.run(
                    """
                    UNWIND $views AS v
                    MATCH (view:View {schema: v.schema, name: v.name})
                    MATCH (f:File {path: v.source_file})
                    MERGE (f)-[:DEFINES]->(view)
                    """,
                    views=chunk,
                )

            for chunk in self._chunks(procs):
                session.run(
                    """
                    UNWIND $procs AS p
                    MERGE (sp:StoredProcedure {schema: p.schema, name: p.name})
                    SET sp.parameters = p.parameters,
                        sp.source_file = p.source_file,
                        sp.source_line = p.source_line,
                        sp.has_dynamic_sql = p.has_dynamic_sql,
                        sp.is_empty = p.is_empty,
                        sp.is_system = p.is_system
                    """,
                    procs=chunk,
                )
                session.run(
                    """
                    UNWIND $procs AS p
                    MATCH (sp:StoredProcedure {schema: p.schema, name: p.name})
                    MATCH (f:File {path: p.source_file})
                    MERGE (f)-[:DEFINES]->(sp)
                    """,
                    procs=chunk,
                )

            for chunk in self._chunks(funcs):
                session.run(
                    """
                    UNWIND $funcs AS fn
                    MERGE (df:DatabaseFunction {schema: fn.schema, name: fn.name})
                    SET df.parameters = fn.parameters,
                        df.return_type = fn.return_type,
                        df.source_file = fn.source_file,
                        df.source_line = fn.source_line
                    """,
                    funcs=chunk,
                )
                session.run(
                    """
                    UNWIND $funcs AS fn
                    MATCH (df:DatabaseFunction {schema: fn.schema, name: fn.name})
                    MATCH (f:File {path: fn.source_file})
                    MERGE (f)-[:DEFINES]->(df)
                    """,
                    funcs=chunk,
                )

            all_deps = []
            for o in objects:
                for dep in o.get("dependencies", []):
                    all_deps.append({
                        "src_schema": o["schema"],
                        "src_name": o["name"],
                        "src_label": o["label"],
                        "target_schema": dep["target_schema"],
                        "target_name": dep["target_name"],
                        "rel": dep["rel"],
                    })

            deps_by_rel: dict[str, list] = {}
            for d in all_deps:
                deps_by_rel.setdefault(d["rel"], []).append(d)

            for rel_type, deps in deps_by_rel.items():
                for chunk in self._chunks(deps):
                    session.run(
                        f"""
                        UNWIND $deps AS d
                        MATCH (src)
                        WHERE (src:View OR src:StoredProcedure OR src:DatabaseFunction)
                        AND src.schema = d.src_schema AND src.name = d.src_name
                        MATCH (target)
                        WHERE (target:Table OR target:View OR target:StoredProcedure OR target:DatabaseFunction)
                        AND target.schema = d.target_schema AND target.name = d.target_name
                        MERGE (src)-[:{rel_type}]->(target)
                        """,
                        deps=chunk,
                    )
