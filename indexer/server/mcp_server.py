"""SA-Helper MCP Server — exposes graph query tools via Model Context Protocol.

Uses FastMCP SDK for protocol handling. Transport: stdio.

Tools exposed:
  - graph_call_chain(function_name, depth=3): Trace call chains from a function
  - graph_impact(entity_name, entity_type="auto"): Analyze entity dependencies
  - graph_schema(): Overview of project structure
  - graph_select_files(task_description): Select files relevant to a task
  - graph_export(entity_name=None, fmt="text"): Export graph data
  - graph_arch_summary(): Architecture summary per controller
  - graph_query(cypher, params, limit): Execute arbitrary Cypher query
  - graph_stats(): Database statistics
"""

from __future__ import annotations

import json
import os
import sys
import logging

from fastmcp import FastMCP

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from graph_db import GraphDB

# Logging to stderr (stdout is used for MCP protocol)
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s [sa-helper-mcp] %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASS = os.environ.get("NEO4J_PASS", "sahelper2026")

_MUTATION_KEYWORDS = ("CREATE", "MERGE", "DELETE", "DETACH", "SET ", "REMOVE", "DROP")
_READ_ONLY_STARTS = ("MATCH", "RETURN", "WITH ", "OPTIONAL MATCH", "UNWIND", "PROFILE", "EXPLAIN", "CYPHER")

mcp = FastMCP("sa-helper-graph")


def _get_db() -> GraphDB:
    """Create a new GraphDB connection."""
    return GraphDB(NEO4J_URI, NEO4J_USER, NEO4J_PASS)


def _json_str(data) -> str:
    """Serialize data to JSON string."""
    if isinstance(data, str):
        return data
    return json.dumps(data, ensure_ascii=False, indent=2)


def _run_query(tool_name: str, method_name: str, *args, **kwargs) -> str:
    """Execute a GraphDB method with proper connection lifecycle."""
    log.info("%s: %s", tool_name, kwargs.get("function_name") or kwargs.get("entity_name") or "")
    db = None
    try:
        db = _get_db()
        result = getattr(db, method_name)(*args, **kwargs)
        return _json_str(result)
    except Exception as e:
        log.error("%s failed: %s", tool_name, e)
        return _json_str({"error": str(e), "tool": tool_name})
    finally:
        if db:
            db.close()


@mcp.tool
def graph_call_chain(function_name: str, depth: int = 3) -> str:
    """Trace call chains starting from a function in the project graph.

    Returns chains of function calls up to the specified depth.
    Use this to understand how code flows from a specific entry point.

    Args:
        function_name: Name of the function to trace calls from.
        depth: Maximum depth of call chain traversal (default: 3).
    """
    return _run_query(
        "graph_call_chain", "query_call_chain",
        function_name, depth=depth,
    )


@mcp.tool
def graph_impact(entity_name: str, entity_type: str = "auto") -> str:
    """Analyze which entities depend on the given entity (class, function, or table).

    Returns a list of dependents with their relationships and files.
    Useful for impact analysis before making changes.

    Args:
        entity_name: Name of the entity to analyze.
        entity_type: Type of entity — "class", "function", "table", or "auto" (default).
    """
    return _run_query(
        "graph_impact", "query_impact",
        entity_name, entity_type=entity_type,
    )


@mcp.tool
def graph_schema(limit: int = 100, offset: int = 0) -> str:
    """Get an overview of the project structure from the graph.

    Returns counts of classes, functions, tables, endpoints, external services,
    plus paginated lists of classes (with inheritance), endpoints, tables, and
    services. Full counts are in `stats`; the `pagination` block reports the
    window and whether results were truncated. Use `offset` to page through.

    Args:
        limit: Max items per entity list (default 100, max 1000).
        offset: Pagination offset into each entity list (default 0).
    """
    return _run_query("graph_schema", "query_schema", limit=limit, offset=offset)


@mcp.tool
def graph_select_files(task_description: str) -> str:
    """Select files relevant to a task description by matching keywords to graph entities.

    Returns a list of file paths sorted by relevance. Includes 1-level expansion
    via CALLS/QUERIES/EXTENDS/IMPORTS relationships.

    Args:
        task_description: Description of the task to find relevant files for.
    """
    return _run_query(
        "graph_select_files", "query_select_files",
        task_description,
    )


@mcp.tool
def graph_export(entity_name: str | None = None, fmt: str = "text") -> str:
    """Export graph data as text, JSON, or Mermaid diagram.

    Optionally focus on a specific entity to get its impact analysis and call chains.

    Args:
        entity_name: Optional entity name to focus the export on.
        fmt: Output format — "text", "json", or "mermaid" (default: text).
    """
    db = None
    try:
        log.info("graph_export: entity=%s format=%s", entity_name, fmt)
        db = _get_db()
        result = db.query_export(entity_name=entity_name, format=fmt)
        return result
    except Exception as e:
        log.error("graph_export failed: %s", e)
        return _json_str({"error": str(e), "tool": "graph_export"})
    finally:
        if db:
            db.close()


@mcp.tool
def graph_arch_summary(limit: int = 20, offset: int = 0) -> str:
    """Get architecture summary: for each controller, trace its services, DAOs, tables, endpoints.

    Returns a structured view of the Controller -> Service -> DAO -> Table layers,
    plus external service dependencies. Paginated over the controller list so the
    response stays within token limits; the `pagination` block reports the total
    controller count and whether results were truncated. Use `offset` to page.

    Args:
        limit: Max controllers to trace per call (default 20, max 1000).
        offset: Pagination offset into the controller list (default 0).
    """
    return _run_query("graph_arch_summary", "query_arch_summary", limit=limit, offset=offset)


@mcp.tool
def graph_query(cypher: str, params: str | None = None, limit: int = 100) -> str:
    """Execute an arbitrary read-only Cypher query against the Neo4j project graph.

    Use for ad-hoc queries not covered by specialized tools: node counts,
    relationship patterns, subgraph extraction, aggregation, etc.

    Args:
        cypher: Cypher query string. Use $param for parameterized values.
        params: Optional JSON string with query parameters, e.g. '{"name": "ShowController"}'.
        limit: Maximum number of rows to return (default: 100, max: 1000).
    """
    db = None
    try:
        log.info("graph_query: %s", cypher[:120])
        if limit > 1000:
            limit = 1000

        # Read-only check
        cypher_upper = cypher.strip().upper()
        if not any(cypher_upper.startswith(kw) for kw in _READ_ONLY_STARTS):
            return _json_str({"error": "Query must start with a read clause (MATCH, RETURN, WITH, OPTIONAL MATCH, UNWIND, PROFILE, EXPLAIN)", "tool": "graph_query"})
        for kw in _MUTATION_KEYWORDS:
            if kw in cypher_upper:
                return _json_str({"error": f"Write operation detected ({kw.strip()}). Only read queries are allowed.", "tool": "graph_query"})

        # Parse params
        query_params = {}
        if params:
            query_params = json.loads(params)

        # Auto-inject LIMIT if not present
        cypher_stripped = cypher.strip().rstrip(";")
        if "LIMIT" not in cypher_stripped.upper():
            cypher_stripped += f"\nLIMIT {limit}"

        db = _get_db()
        with db.driver.session() as session:
            result = session.run(cypher_stripped, query_params)
            rows = []
            for record in result:
                row = {}
                for key in record.keys():
                    val = record[key]
                    if hasattr(val, "__iter__") and not isinstance(val, (str, list, dict)):
                        row[key] = list(val)
                    else:
                        row[key] = val
                rows.append(row)

        return _json_str({
            "rows": rows,
            "count": len(rows),
            "query": cypher_stripped,
        })
    except Exception as e:
        log.error("graph_query failed: %s", e)
        return _json_str({"error": str(e), "tool": "graph_query"})
    finally:
        if db:
            db.close()


@mcp.tool
def graph_stats() -> str:
    """Get database statistics: node counts by label and relationship counts by type.

    Returns total node and relationship counts across all entity types in the graph.
    Useful for quick health checks and understanding graph coverage.
    """
    return _run_query("graph_stats", "get_stats")


@mcp.tool
def graph_db_schema(schema_name: str | None = None) -> str:
    """Get all DB objects (tables, views, stored procedures, functions) from the graph.

    Returns objects with types, schemas, columns, and parameters.
    Optionally filter by schema name.

    Args:
        schema_name: Optional schema name to filter (e.g. "public", "dbo", "history").
    """
    kwargs = {}
    if schema_name:
        kwargs["schema_name"] = schema_name
    return _run_query("graph_db_schema", "query_db_schema", **kwargs)


@mcp.tool
def graph_db_lineage(object_name: str, direction: str = "both") -> str:
    """Get upstream and downstream lineage for a DB object.

    Shows what tables/views/SPs this object depends on (upstream)
    and what depends on it (downstream). Useful for understanding
    the full dependency chain of a database object.

    Args:
        object_name: Name of the DB object (table, view, SP, or function).
        direction: "upstream" (what it uses), "downstream" (what uses it), or "both" (default).
    """
    return _run_query(
        "graph_db_lineage", "query_db_lineage",
        object_name, direction=direction,
    )


@mcp.tool
def graph_db_orphans() -> str:
    """Find DB objects with no connections — unused tables, views, and stored procedures.

    Returns DB objects defined in DDL that have no relationships at all
    (no code references, no cross-object dependencies). Useful for identifying
    completely unused database objects.
    """
    return _run_query("graph_db_orphans", "query_db_orphans")


@mcp.tool
def graph_db_unresolved() -> str:
    """Find code SQL references that don't match any DDL object.

    Returns table/SP names referenced in code (QUERIES, CALLS_SP) that
    have no corresponding DDL definition in the graph.
    Useful for finding missing DDL files or typos in code.
    """
    return _run_query("graph_db_unresolved", "query_db_unresolved")


@mcp.tool
def graph_db_impact(object_name: str) -> str:
    """Transitive impact analysis for a DB object.

    Finds all views, stored procedures, functions, and code functions
    that transitively depend on the given DB object (up to 3 hops).
    Useful for assessing the blast radius of a schema change.

    Args:
        object_name: Name of the DB object to analyze.
    """
    return _run_query("graph_db_impact", "query_db_impact", object_name)


if __name__ == "__main__":
    # Verify Neo4j connectivity at startup
    try:
        db = _get_db()
        db.verify_connection()
        db.close()
        log.info("Neo4j connection verified at %s", NEO4J_URI)
    except Exception as e:
        log.warning("Neo4j not available at startup: %s. Tools will return errors until Neo4j is reachable.", e)

    mcp.run(transport="stdio")
