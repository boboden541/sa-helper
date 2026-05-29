"""GraphDB facade — assembles mixin classes into a single GraphDB interface.

Usage: from graph_db import GraphDB
"""

from __future__ import annotations

from graph_db._base import GraphDBBase, BATCH_SIZE, _label_var
from graph_db._writer import WriterMixin
from graph_db._linker import LinkerMixin
from graph_db._maintenance import MaintenanceMixin
from graph_db._queries import QueryMixin

__all__ = ["GraphDB", "BATCH_SIZE", "_label_var"]


class GraphDB(GraphDBBase, WriterMixin, LinkerMixin, MaintenanceMixin, QueryMixin):
    """Unified Neo4j graph database client.

    Composed from mixin classes:
    - GraphDBBase: driver init, close, verify, clear_graph, create_indexes
    - WriterMixin: 16 create_* methods for nodes
    - LinkerMixin: link_config_to_classes, mark_dynamic_sql, link_cross_project
    - MaintenanceMixin: get_stats, delete_file_nodes, cleanup_orphan_nodes,
                        save/get_index_state, link_project_to_files,
                        link_files_to_projects, delete_project, update_project_stats
    - QueryMixin: 15 query_* methods for reading graph data
    """

    def refresh_global_links(self):
        """Re-run all global linking steps after incremental update."""
        self.create_inheritance()
        self.create_external_references()
        self.resolve_imports()
        self.mark_dynamic_sql()
        self.link_cross_project()
        self.link_config_to_classes()
