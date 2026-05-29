"""MaintenanceMixin — CRUD operations, graph cleanup, and index state management."""

from __future__ import annotations


class MaintenanceMixin:

    def link_project_to_files(self, project_name: str):
        with self.driver.session() as session:
            session.run(
                """
                MATCH (p:Project {name: $name})
                MATCH (f:File)
                MERGE (p)-[:HAS_FILE]->(f)
                """,
                name=project_name,
            )

    def get_stats(self) -> dict:
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (n)
                RETURN labels(n)[0] AS label, count(n) AS count
                ORDER BY count DESC
                """
            )
            stats = {record["label"]: record["count"] for record in result}

            rel_result = session.run(
                """
                MATCH ()-[r]->()
                RETURN type(r) AS type, count(r) AS count
                ORDER BY count DESC
                """
            )
            stats["relationships"] = {
                record["type"]: record["count"] for record in rel_result
            }
            return stats

    def delete_file_nodes(self, file_paths: list[str]):
        """Delete File nodes and all their DEFINES children for given paths."""
        if not file_paths:
            return
        with self.driver.session() as session:
            for chunk in self._chunks(file_paths):
                session.run(
                    """
                    UNWIND $paths AS path
                    MATCH (f:File {path: path})
                    OPTIONAL MATCH (f)-[:DEFINES]->(n)
                    DETACH DELETE n
                    DETACH DELETE f
                    """,
                    paths=chunk,
                )

    def cleanup_orphan_nodes(self):
        """Remove singleton nodes that lost all relationships after file deletion."""
        with self.driver.session() as session:
            session.run(
                """
                MATCH (sp:StoredProcedure)
                WHERE sp.schema IS NULL
                DETACH DELETE sp
                """
            )
            session.run(
                """
                MATCH (t:Table)
                WHERE t.schema IS NULL
                DETACH DELETE t
                """
            )
            session.run(
                """
                MATCH (n)
                WHERE (n:Import OR n:ExternalClass)
                AND NOT (n)--()
                DELETE n
                """
            )
            session.run(
                """
                MATCH (n)
                WHERE (n:Table OR n:ExternalService OR n:FrameworkComponent)
                AND NOT (n)--()
                DELETE n
                """
            )

    def save_index_state(self, project_name: str, commit_sha: str):
        """Save last indexed commit SHA on Project node."""
        with self.driver.session() as session:
            session.run(
                """
                MATCH (p:Project {name: $name})
                SET p.last_indexed_commit = $sha
                """,
                name=project_name, sha=commit_sha,
            )

    def get_index_state(self, project_name: str) -> str | None:
        """Get last indexed commit SHA from Project node."""
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (p:Project {name: $name})
                RETURN p.last_indexed_commit AS sha
                """,
                name=project_name,
            )
            for record in result:
                return record["sha"]
        return None

    def resolve_table_view_duplicates(self):
        """Redirect all relationships from Table to matching View where both exist."""
        with self.driver.session() as session:
            # 1. Function→Table → Function→View
            session.run("""
                MATCH (f:Function)-[r:QUERIES]->(t:Table)
                WHERE EXISTS { MATCH (v:View {schema: t.schema, name: t.name}) }
                MATCH (v:View {schema: t.schema, name: t.name})
                MERGE (f)-[:QUERIES]->(v)
                DELETE r
            """)

            # 2. StoredProcedure→Table → StoredProcedure→View
            session.run("""
                MATCH (sp:StoredProcedure)-[r:QUERIES]->(t:Table)
                WHERE EXISTS { MATCH (v:View {schema: t.schema, name: t.name}) }
                MATCH (v:View {schema: t.schema, name: t.name})
                MERGE (sp)-[:QUERIES]->(v)
                DELETE r
            """)
            session.run("""
                MATCH (sp:StoredProcedure)-[r:INSERTS_INTO]->(t:Table)
                WHERE EXISTS { MATCH (v:View {schema: t.schema, name: t.name}) }
                MATCH (v:View {schema: t.schema, name: t.name})
                MERGE (sp)-[:INSERTS_INTO]->(v)
                DELETE r
            """)
            session.run("""
                MATCH (sp:StoredProcedure)-[r:UPDATES]->(t:Table)
                WHERE EXISTS { MATCH (v:View {schema: t.schema, name: t.name}) }
                MATCH (v:View {schema: t.schema, name: t.name})
                MERGE (sp)-[:UPDATES]->(v)
                DELETE r
            """)

            # 3. View→DEPENDS_ON→Table(view_name) → View→DEPENDS_ON→View
            session.run("""
                MATCH (src:View)-[r:DEPENDS_ON]->(t:Table)
                WHERE EXISTS { MATCH (v:View {schema: t.schema, name: t.name}) }
                MATCH (v:View {schema: t.schema, name: t.name})
                MERGE (src)-[:DEPENDS_ON]->(v)
                DELETE r
            """)

            # 4. Remove orphan Table duplicates
            session.run("""
                MATCH (t:Table)
                WHERE NOT (t)--()
                  AND EXISTS { MATCH (v:View {schema: t.schema, name: t.name}) }
                DETACH DELETE t
            """)

    def link_files_to_projects(self):
        """Link each File to its corresponding Project based on path prefix."""
        with self.driver.session() as session:
            session.run("""
                MATCH (f:File), (p:Project)
                WHERE f.path STARTS WITH p.name + '/'
                   OR split(f.path, '/')[0] = p.name
                MERGE (p)-[:HAS_FILE]->(f)
            """)

    def delete_project(self, name: str):
        """Remove a Project node without touching its files."""
        with self.driver.session() as session:
            session.run("MATCH (p:Project {name: $name}) DELETE p", name=name)

    def update_project_stats(self):
        """Update Project node stats based on linked files."""
        with self.driver.session() as session:
            session.run("""
                MATCH (p:Project)-[:HAS_FILE]->(f:File)
                WITH p, count(f) AS file_count, sum(f.lines) AS line_count
                SET p.total_files = file_count,
                    p.total_lines = line_count
            """)
