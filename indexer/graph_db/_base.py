"""GraphDB base — driver initialization, connection lifecycle, and shared utilities."""

from __future__ import annotations

import re

from neo4j import GraphDatabase

BATCH_SIZE = 2000

_LABEL_MAP = {
    "View": "View",
    "StoredProcedure": "StoredProcedure",
    "DatabaseFunction": "DatabaseFunction",
}


def _label_var(label: str) -> str:
    return _LABEL_MAP.get(label, "View")


def _url_segments(url: str) -> list[str]:
    """Split URL into normalized segments for endpoint matching."""
    url = url.strip('/')
    # Split by / and - first
    parts = re.split(r'[/\-]+', url)
    # Then split camelCase: autocompleteMore → autocomplete, More
    segments = []
    for part in parts:
        if not part:
            continue
        # Split on transitions: lowercase→uppercase (camelCase boundary)
        sub = re.sub(r'([a-z])([A-Z])', r'\1 \2', part)
        segments.extend(s.lower() for s in sub.split() if s)
    return segments


def _urls_match(frontend_url: str, backend_route: str) -> bool:
    """Check if frontend URL matches backend endpoint route via segment comparison.

    Handles: prefix differences (/api/ vs none), trailing slashes, / vs - separators.
    """
    fe_segs = _url_segments(frontend_url)
    be_segs = _url_segments(backend_route)

    if not fe_segs or not be_segs:
        return False

    if fe_segs == be_segs:
        return True

    # Backend segments are suffix of frontend (frontend has extra prefix like 'api')
    if len(fe_segs) > len(be_segs):
        return fe_segs[-len(be_segs):] == be_segs

    # Frontend segments are suffix of backend (backend has extra suffix)
    if len(be_segs) > len(fe_segs):
        return be_segs[-len(fe_segs):] == fe_segs

    return False


class GraphDBBase:
    def __init__(self, uri: str, user: str, password: str):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))

    @staticmethod
    def _chunks(data: list, size: int = BATCH_SIZE):
        for i in range(0, len(data), size):
            yield data[i:i + size]

    def close(self):
        self.driver.close()

    def verify_connection(self):
        with self.driver.session() as session:
            result = session.run("RETURN 1")
            result.consume()

    def clear_graph(self):
        with self.driver.session() as session:
            session.run("MATCH (n) DETACH DELETE n")

    def create_indexes(self):
        """Create indexes for fast lookups during bulk writes."""
        with self.driver.session() as session:
            indexes = [
                "CREATE INDEX IF NOT EXISTS FOR (f:Function) ON (f.name)",
                "CREATE INDEX IF NOT EXISTS FOR (f:Function) ON (f.file)",
                "CREATE INDEX IF NOT EXISTS FOR (c:Class) ON (c.name)",
                "CREATE INDEX IF NOT EXISTS FOR (c:Class) ON (c.file)",
                "CREATE INDEX IF NOT EXISTS FOR (file:File) ON (file.path)",
                "CREATE INDEX IF NOT EXISTS FOR (dir:Directory) ON (dir.path)",
                "CREATE INDEX IF NOT EXISTS FOR (t:Table) ON (t.schema, t.name)",
                "CREATE INDEX IF NOT EXISTS FOR (v:View) ON (v.schema, v.name)",
                "CREATE INDEX IF NOT EXISTS FOR (sp:StoredProcedure) ON (sp.schema, sp.name)",
                "CREATE INDEX IF NOT EXISTS FOR (df:DatabaseFunction) ON (df.schema, df.name)",
            ]
            for idx in indexes:
                session.run(idx)
