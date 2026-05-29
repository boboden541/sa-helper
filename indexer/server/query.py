"""SA-Helper Graph Query CLI — query the Neo4j project graph from the command line."""

from __future__ import annotations

import argparse
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from graph_db import GraphDB

DEFAULT_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
DEFAULT_USER = os.environ.get("NEO4J_USER", "neo4j")
DEFAULT_PASS = os.environ.get("NEO4J_PASS", "sahelper2026")


def connect_db(args) -> GraphDB:
    """Connect to Neo4j, return GraphDB or exit with error."""
    try:
        db = GraphDB(args.neo4j_uri, args.neo4j_user, args.neo4j_pass)
        db.verify_connection()
        return db
    except Exception as e:
        print(f"ERROR: Cannot connect to Neo4j at {args.neo4j_uri}", file=sys.stderr)
        print(f"  {e}", file=sys.stderr)
        sys.exit(1)


def fmt_output(data, fmt: str):
    """Print data in the requested format."""
    if fmt == "json":
        if isinstance(data, str):
            print(data)
        else:
            print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        if isinstance(data, str):
            print(data)
        else:
            print(json.dumps(data, ensure_ascii=False, indent=2))


def cmd_call_chain(args):
    db = connect_db(args)
    try:
        result = db.query_call_chain(args.function_name, depth=args.depth)
        if args.format == "mermaid":
            lines = ["graph LR"]
            root = result["root"]
            if root:
                seen = set()
                for ch in result["chains"]:
                    for i in range(len(ch["path"]) - 1):
                        src = ch["path"][i].replace('"', "'")
                        dst = ch["path"][i + 1].replace('"', "'")
                        key = (src, dst)
                        if key not in seen:
                            seen.add(key)
                            lines.append(f'    {src}["{src}"] --> {dst}["{dst}"]')
                if len(lines) == 1:
                    lines.append(f'    {root["name"]}["{root["name"]}"]')
            print("\n".join(lines))
        elif args.format == "json":
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            # text
            root = result["root"]
            if not root:
                print(f"Function '{args.function_name}' not found.")
                return
            print(f"Call chains from {root['name']} ({root['file']}):")
            if not result["chains"]:
                print("  No outgoing calls found.")
            for ch in result["chains"]:
                print(f"  {' -> '.join(ch['path'])}")
    finally:
        db.close()


def cmd_impact(args):
    db = connect_db(args)
    try:
        result = db.query_impact(args.entity_name, entity_type=args.type)
        if args.format == "json":
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            ent = result["entity"]
            if not ent:
                print(f"Entity '{args.entity_name}' not found.")
                return
            print(f"Impact analysis for {ent['name']} ({ent['type']}):")
            if not result["dependents"]:
                print("  No dependents found.")
            for d in result["dependents"]:
                print(f"  - {d['name']} ({d['type']}) [{d['relation']}] in {d['file']}")
    finally:
        db.close()


def cmd_schema(args):
    db = connect_db(args)
    try:
        result = db.query_schema()
        if args.format == "json":
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.format == "mermaid":
            lines = ["graph LR"]
            for cls in result["classes"][:30]:
                name = cls["name"].replace('"', "'")
                lines.append(f'    {name}["{name}"]')
            for ep in result["endpoints"][:20]:
                name = (ep.get("handler") or ep.get("path", "?")).replace('"', "'")
                lines.append(f'    {name}["{name}"]')
            if len(lines) == 1:
                lines.append("    Empty[Graph is empty]")
            print("\n".join(lines))
        else:
            stats = result["stats"]
            print("=== Project Structure ===")
            print(" | ".join(f"{k}: {v}" for k, v in stats.items()))
            print()
            if result["classes"]:
                print(f"Classes ({len(result['classes'])}):")
                for cls in result["classes"][:20]:
                    line = f"  {cls['name']} ({cls['file']})"
                    if cls.get("parent_class"):
                        line += f" extends {cls['parent_class']}"
                    print(line)
                if len(result["classes"]) > 20:
                    print(f"  ... and {len(result['classes']) - 20} more")
            if result["endpoints"]:
                print(f"\nEndpoints ({len(result['endpoints'])}):")
                for ep in result["endpoints"][:20]:
                    print(f"  {ep.get('method', '?')} {ep.get('path', '?')} -> {ep.get('handler', '?')} ({ep['file']})")
            if result["tables"]:
                print(f"\nTables ({len(result['tables'])}):")
                for t in result["tables"]:
                    print(f"  {t['name']}")
            if result["external_services"]:
                print(f"\nExternal Services ({len(result['external_services'])}):")
                for svc in result["external_services"]:
                    print(f"  {svc['name']} ({svc.get('type', '?')})")
    finally:
        db.close()


def cmd_select_files(args):
    db = connect_db(args)
    try:
        files = db.query_select_files(args.task_description)
        if args.format == "json":
            print(json.dumps(files, ensure_ascii=False, indent=2))
        else:
            if not files:
                print("No matching files found. Fallback to full repomix recommended.")
            else:
                print(f"Selected {len(files)} files:")
                for f in files:
                    print(f"  {f}")
    finally:
        db.close()


def cmd_export(args):
    db = connect_db(args)
    try:
        result = db.query_export(entity_name=args.entity, format=args.format)
        print(result)
    finally:
        db.close()


def cmd_arch_summary(args):
    db = connect_db(args)
    try:
        summaries = db.query_arch_summary()
        if args.format == "json":
            print(json.dumps(summaries, ensure_ascii=False, indent=2))
        elif args.format == "mermaid":
            lines = ["graph LR"]
            for s in summaries:
                ctrl = s["controller"].replace('"', "'")
                for svc in s["services"]:
                    svc_safe = svc.replace('"', "'")
                    lines.append(f'    {ctrl}["{ctrl}"] -->|calls| {svc_safe}["{svc_safe}"]')
                for dao in s["daos"]:
                    dao_safe = dao.replace('"', "'")
                    lines.append(f'    {ctrl} -->|DAO| {dao_safe}["{dao_safe}"]')
                for t in s["tables"]:
                    t_safe = t.replace('"', "'")
                    lines.append(f'    {ctrl} -->|queries| {t_safe}["{t_safe}"]')
            if len(lines) == 1:
                lines.append("    Empty[No controllers found]")
            print("\n".join(lines))
        else:
            if not summaries:
                print("No controllers found in graph.")
                return
            print(f"=== Architecture Summary ({len(summaries)} controllers) ===\n")
            for s in summaries:
                print(f"--- {s['controller']} ({s['file']}) ---")
                if s["endpoints"]:
                    print(f"  Endpoints ({len(s['endpoints'])}):")
                    for ep in s["endpoints"]:
                        print(f"    {ep}")
                if s["services"]:
                    print(f"  Services: {', '.join(s['services'])}")
                if s["daos"]:
                    print(f"  DAO: {', '.join(s['daos'])}")
                if s["tables"]:
                    print(f"  Tables: {', '.join(s['tables'])}")
                if s["external_services"]:
                    print(f"  External: {', '.join(s['external_services'])}")
                print()
    finally:
        db.close()


def cmd_db_schema(args):
    db = connect_db(args)
    try:
        result = db.query_db_schema(getattr(args, "schema_name", None))
        if args.format == "json":
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            objects = result["objects"]
            if not objects:
                print("No DB objects found.")
                return
            print(f"=== DB Schema ({result['count']} objects) ===\n")
            by_type = {}
            for obj in objects:
                by_type.setdefault(obj["type"], []).append(obj)
            for type_name, items in sorted(by_type.items()):
                print(f"{type_name} ({len(items)}):")
                for obj in items:
                    schema = obj.get("schema", "")
                    name = obj["name"]
                    line = f"  {schema}.{name}" if schema else f"  {name}"
                    if obj.get("columns"):
                        line += f" ({len(obj['columns'])} columns)"
                    print(line)
                print()
    finally:
        db.close()


def cmd_db_lineage(args):
    db = connect_db(args)
    try:
        result = db.query_db_lineage(args.object_name, direction=args.direction)
        if args.format == "json":
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            obj = result["object"]
            if not obj:
                print(f"DB object '{args.object_name}' not found.")
                return
            print(f"Lineage for {obj['schema']}.{obj['name']} ({obj['type']}):\n")
            if result["upstream"]:
                print(f"Upstream dependencies ({len(result['upstream'])}):")
                for u in result["upstream"]:
                    print(f"  <- {u.get('schema', '')}.{u['name']} ({u['type']}) [{u['relation']}]")
            else:
                print("Upstream: none")
            if result["downstream"]:
                print(f"\nDownstream dependents ({len(result['downstream'])}):")
                for d in result["downstream"]:
                    loc = f" in {d['file']}" if d.get("file") else ""
                    print(f"  -> {d.get('schema', '')}.{d['name']} ({d['type']}) [{d['relation']}]{loc}")
            else:
                print("\nDownstream: none")
    finally:
        db.close()


def cmd_db_orphans(args):
    db = connect_db(args)
    try:
        result = db.query_db_orphans()
        if args.format == "json":
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            if not result:
                print("No orphan DB objects found.")
                return
            print(f"=== Orphan DB Objects ({len(result)}) ===\n")
            for obj in result:
                schema = obj.get("schema", "")
                name = f"{schema}.{obj['name']}" if schema else obj["name"]
                print(f"  {name} ({obj['type']}) — {obj.get('source_file', '?')}")
    finally:
        db.close()


def cmd_db_unresolved(args):
    db = connect_db(args)
    try:
        result = db.query_db_unresolved()
        if args.format == "json":
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            if not result:
                print("No unresolved references found.")
                return
            print(f"=== Unresolved DB References ({len(result)}) ===\n")
            for ref in result:
                print(f"  {ref['name']} [{ref['relation']}] referenced by {ref['function']} in {ref['file']}")
    finally:
        db.close()


def cmd_db_impact(args):
    db = connect_db(args)
    try:
        result = db.query_db_impact(args.object_name)
        if args.format == "json":
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            obj = result["object"]
            if not obj:
                print(f"DB object '{args.object_name}' not found.")
                return
            print(f"Impact analysis for {obj['schema']}.{obj['name']} ({obj['type']}):")
            impacted = result["impacted"]
            if not impacted:
                print("  No dependents found.")
            else:
                print(f"  {len(impacted)} impacted entities:")
                for imp in impacted:
                    schema = imp.get("schema", "")
                    name = f"{schema}.{imp['name']}" if schema else imp["name"]
                    loc = f" in {imp['file']}" if imp.get("file") else ""
                    print(f"  {'  ' * (imp['depth'] - 1)}{name} ({imp['type']}){loc}")
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(
        description="SA-Helper Graph Query CLI — query the Neo4j project graph"
    )
    parser.add_argument("--neo4j-uri", default=DEFAULT_URI, help="Neo4j Bolt URI")
    parser.add_argument("--neo4j-user", default=DEFAULT_USER, help="Neo4j username")
    parser.add_argument("--neo4j-pass", default=DEFAULT_PASS, help="Neo4j password")

    sub = parser.add_subparsers(dest="command", help="Available commands")

    # call-chain
    p_cc = sub.add_parser("call-chain", help="Trace call chains from a function")
    p_cc.add_argument("function_name", help="Function name to trace from")
    p_cc.add_argument("--depth", type=int, default=3, help="Max depth (default: 3)")
    p_cc.add_argument("--format", choices=["text", "json", "mermaid"], default="text")

    # impact
    p_imp = sub.add_parser("impact", help="Analyze impact of an entity")
    p_imp.add_argument("entity_name", help="Entity name to analyze")
    p_imp.add_argument("--type", default="auto", choices=["class", "function", "table", "auto"])
    p_imp.add_argument("--format", choices=["text", "json"], default="text")

    # schema
    p_sch = sub.add_parser("schema", help="Overview of project structure")
    p_sch.add_argument("--format", choices=["text", "json", "mermaid"], default="text")

    # select-files
    p_sf = sub.add_parser("select-files", help="Select files relevant to a task")
    p_sf.add_argument("task_description", help="Task description for file selection")
    p_sf.add_argument("--format", choices=["text", "json"], default="text")

    # export
    p_exp = sub.add_parser("export", help="Export graph data")
    p_exp.add_argument("--entity", default=None, help="Focus on specific entity")
    p_exp.add_argument("--format", choices=["text", "json", "mermaid"], default="text")

    # arch-summary
    p_arch = sub.add_parser("arch-summary", help="Architecture summary: controllers, services, DAOs, tables")
    p_arch.add_argument("--format", choices=["text", "json", "mermaid"], default="text")

    # db-schema
    p_dbsch = sub.add_parser("db-schema", help="All DB objects with types, schemas, columns")
    p_dbsch.add_argument("--schema-name", default=None, help="Filter by schema name (e.g. dbo)")
    p_dbsch.add_argument("--format", choices=["text", "json"], default="text")

    # db-lineage
    p_dblin = sub.add_parser("db-lineage", help="Upstream/downstream lineage for a DB object")
    p_dblin.add_argument("object_name", help="DB object name")
    p_dblin.add_argument("--direction", choices=["upstream", "downstream", "both"], default="both",
                         help="Direction: upstream, downstream, or both (default)")
    p_dblin.add_argument("--format", choices=["text", "json"], default="text")

    # db-orphans
    p_dborp = sub.add_parser("db-orphans", help="DB objects with no links to code")
    p_dborp.add_argument("--format", choices=["text", "json"], default="text")

    # db-unresolved
    p_dbunr = sub.add_parser("db-unresolved", help="Code SQL references not found in DDL")
    p_dbunr.add_argument("--format", choices=["text", "json"], default="text")

    # db-impact
    p_dbimp = sub.add_parser("db-impact", help="Transitive impact analysis for a DB object")
    p_dbimp.add_argument("object_name", help="DB object name")
    p_dbimp.add_argument("--format", choices=["text", "json"], default="text")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    dispatch = {
        "call-chain": cmd_call_chain,
        "impact": cmd_impact,
        "schema": cmd_schema,
        "select-files": cmd_select_files,
        "export": cmd_export,
        "arch-summary": cmd_arch_summary,
        "db-schema": cmd_db_schema,
        "db-lineage": cmd_db_lineage,
        "db-orphans": cmd_db_orphans,
        "db-unresolved": cmd_db_unresolved,
        "db-impact": cmd_db_impact,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
