"""LinkerMixin — methods that create relationships between existing nodes."""

from __future__ import annotations

from graph_db._base import _urls_match


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

            # 5b. URL-based Endpoint matching via ExternalService.http_url (Python normalization)
            self._link_calls_api_by_url(session)

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

    def _link_calls_api_by_url(self, session):
        """Create CALLS_API links from ExternalService.http_url to Endpoint using segment matching."""
        result = session.run("""
            MATCH (f:Function)-[:CALLS_EXTERNAL]->(s:ExternalService)
            WHERE s.http_url IS NOT NULL
            RETURN f.name AS func_name, f.file AS func_file, s.http_url AS http_url
        """)
        services = [dict(record) for record in result]

        if not services:
            return

        ep_result = session.run("MATCH (e:Endpoint) RETURN e.route AS route, e.file AS file")
        endpoints = [dict(record) for record in ep_result]

        matches = []
        for svc in services:
            for ep in endpoints:
                if ep["route"] and _urls_match(svc["http_url"], ep["route"]):
                    matches.append({
                        "func_name": svc["func_name"],
                        "func_file": svc["func_file"],
                        "http_url": svc["http_url"],
                        "endpoint_route": ep["route"],
                        "endpoint_file": ep["file"],
                    })
                    break

        if not matches:
            return

        for chunk in self._chunks(matches):
            session.run(
                """
                UNWIND $matches AS m
                MATCH (f:Function {name: m.func_name, file: m.func_file})
                MATCH (e:Endpoint {route: m.endpoint_route, file: m.endpoint_file})
                MERGE (f)-[:CALLS_API {source: 'url_match', url: m.http_url}]->(e)
                """,
                matches=chunk,
            )
