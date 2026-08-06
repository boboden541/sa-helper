"""SA-Helper Graph Indexer — builds a Neo4j graph from project source code."""

from __future__ import annotations

import argparse
import sys
import os
import shutil
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed

# Allow running from project root: python indexer/main.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scanner import scan, is_supported_file, detect_stack
from graph_db import GraphDB
from git_utils import get_head_commit, get_changed_files, is_git_repo
from semgrep_indexer import SemgrepIndexer
from collections import Counter


_WORKER_INDEXER = None


def _get_worker_indexer() -> SemgrepIndexer:
    global _WORKER_INDEXER
    if _WORKER_INDEXER is None:
        _WORKER_INDEXER = SemgrepIndexer()
    return _WORKER_INDEXER


def _parse_file(task: tuple) -> dict | None:
    """Worker function for parallel parsing. Runs in child process."""
    abs_path, lang, rel_path, semgrep_ran, sg_payload = task

    try:
        with open(abs_path, "rb") as f:
            source = f.read()
    except OSError:
        return None

    line_count = source.count(b"\n") + 1

    try:
        indexer = _get_worker_indexer()

        # SQL DDL — всегда через DDL-парсер (сущности — таблицы/объекты БД).
        if lang == "sql_ddl" or rel_path.endswith(".sql"):
            sql_res = indexer.parse_sql_ddl(abs_path, rel_path)
            result = {
                "classes": [], "functions": [], "imports": [], "calls": [],
                "endpoints": [], "external_services": [], "framework_usage": [],
                "tables": sql_res.get("tables", []),
                "db_objects": sql_res.get("db_objects", []),
                "config_entries": [], "scheduled_tasks": [],
            }
        elif semgrep_ran:
            # Semgrep-путь: сущности — из single-pass находок (без subprocess в воркере),
            # отношения (импорты/встроенный SQL/HTTP) — из regex.
            code_rels = indexer.parse_code_file_relationships(abs_path, lang, rel_path)
            sg = sg_payload or {}
            result = {
                "classes": sg.get("classes", []),
                "functions": sg.get("functions", []),
                "endpoints": sg.get("endpoints", []),
                "tables": sg.get("tables", []) + code_rels.get("tables", []),
                "imports": code_rels.get("imports", []),
                "calls": code_rels.get("calls", []),
                "external_services": code_rels.get("external_services", []),
                "db_objects": code_rels.get("db_objects", []),
                "framework_usage": [],
                "config_entries": [], "scheduled_tasks": [],
            }
        else:
            # Фолбэк на Tree-sitter (Semgrep не запускался) — прежнее поведение.
            res_dict = indexer.run_native_tree_sitter([(abs_path, lang, rel_path)])
            result = {
                "classes": res_dict.get("classes", []),
                "functions": res_dict.get("functions", []),
                "imports": res_dict.get("imports", []),
                "calls": res_dict.get("calls", []),
                "tables": res_dict.get("tables", []),
                "endpoints": res_dict.get("endpoints", []),
                "external_services": res_dict.get("external_services", []),
                "framework_usage": res_dict.get("framework_usage", []),
                "db_objects": res_dict.get("db_objects", []),
                "config_entries": res_dict.get("config_entries", []),
                "scheduled_tasks": res_dict.get("scheduled_tasks", []),
            }

    except Exception as e:
        return {
            "file_meta": {
                "rel_path": rel_path,
                "language": lang,
                "lines": line_count,
                "bytes": len(source),
            },
            "parsed": None,
            "error": f"{type(e).__name__}: {e}",
        }

    return {
        "file_meta": {
            "rel_path": rel_path,
            "language": lang,
            "lines": line_count,
            "bytes": len(source),
        },
        "parsed": result,
    }



def _connect_db(neo4j_uri, neo4j_user, neo4j_pass):
    """Connect to Neo4j or exit."""
    db = GraphDB(neo4j_uri, neo4j_user, neo4j_pass)
    try:
        db.verify_connection()
    except Exception as e:
        print(f"ERROR: Cannot connect to Neo4j at {neo4j_uri}")
        print(f"  {e}")
        print(f"\nMake sure Neo4j is running: docker compose up -d")
        db.close()
        sys.exit(1)
    return db


def _detect_default_schema(db_objects: list[dict], tables: list[dict]) -> str | None:
    """Auto-detect default schema from DDL data — returns the most common schema."""
    schemas = []
    for o in db_objects:
        if o.get("schema"):
            schemas.append(o["schema"])
    for t in tables:
        if t.get("schema"):
            schemas.append(t["schema"])
    if not schemas:
        return None
    most_common = Counter(schemas).most_common(1)
    return most_common[0][0] if most_common else None


def _detect_projects(root: Path, db_schema_paths: list[str] | None = None) -> list[dict]:
    """Detect sub-projects from root directory structure + db-schema paths.

    A sub-project is a first-level subdirectory that contains parseable files.
    DDL schema directories passed via --db-schema are also treated as projects.
    """
    projects = []

    # 1. Sub-projects from root directory
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        if child.name.startswith('.'):
            continue
        sample = scan(str(child))
        if not sample:
            continue
        projects.append({
            "name": child.name,
            "path": str(child),
            "root": str(child),
            "type": "code",
        })

    # 2. DDL schema projects (from --db-schema CLI arg)
    if db_schema_paths:
        for schema_path in db_schema_paths:
            schema_root = Path(schema_path).resolve()
            if schema_root.exists():
                projects.append({
                    "name": schema_root.name,
                    "path": str(schema_root),
                    "root": str(schema_root),
                    "type": "ddl",
                })

    return projects


def _parse_files_parallel(root: Path, file_tasks: list[tuple],
                          semgrep_ran: bool = False, sg_by_file: dict | None = None) -> tuple:
    """Parse files in parallel, return aggregated results."""
    all_files_meta = []
    all_classes = []
    all_functions = []
    all_imports = []
    all_calls = []
    all_tables = []
    all_sql_candidates = []
    all_endpoints = []
    all_external_services = []
    all_framework_usage = []
    all_config_entries = []
    all_scheduled_tasks = []
    all_db_objects = []
    total_lines = 0
    parse_errors = []
    skipped_by_lang = {}

    with ProcessPoolExecutor() as executor:
        futures = {}
        for t in file_tasks:
            abs_path, lang, rel_path = t
            payload = sg_by_file.get(os.path.normpath(rel_path)) if semgrep_ran else None
            futures[executor.submit(
                _parse_file, (abs_path, lang, rel_path, semgrep_ran, payload))] = rel_path
        done_count = 0
        total = len(futures)
        bar_length = 30

        for future in as_completed(futures):
            done_count += 1
            if total <= 100 or done_count % 20 == 0 or done_count == total:
                percent = (done_count / total) * 100 if total > 0 else 100
                filled = int(bar_length * done_count // total) if total > 0 else bar_length
                bar = "█" * filled + "░" * (bar_length - filled)
                sys.stdout.write(f"\r  Parsing files: [{bar}] {percent:5.1f}% ({done_count}/{total})")
                sys.stdout.flush()
                if done_count == total:
                    sys.stdout.write("\n")

            result = future.result()

            if result is None:
                continue

            meta = result["file_meta"]
            total_lines += meta["lines"]
            all_files_meta.append(meta)

            if "error" in result:
                parse_errors.append((meta["rel_path"], meta["language"], result["error"]))
                skipped_by_lang[meta["language"]] = skipped_by_lang.get(meta["language"], 0) + 1
                continue

            parsed = result["parsed"]
            if parsed is None:
                continue

            all_classes.extend(parsed["classes"])
            all_functions.extend(parsed["functions"])
            all_imports.extend(parsed["imports"])
            all_calls.extend(parsed["calls"])
            all_tables.extend(parsed["tables"])
            all_sql_candidates.extend(parsed.get("sql_candidates", []))
            all_endpoints.extend(parsed["endpoints"])
            all_external_services.extend(parsed["external_services"])
            all_framework_usage.extend(parsed["framework_usage"])
            all_config_entries.extend(parsed.get("config_entries", []))
            all_scheduled_tasks.extend(parsed.get("scheduled_tasks", []))
            all_db_objects.extend(parsed.get("db_objects", []))

    if parse_errors:
        print(f"\n  WARNING: {len(parse_errors)} files failed to parse:")
        shown = 0
        for path, lang, err in parse_errors:
            if shown < 20:
                print(f"    {path} ({lang}) — {err}")
            shown += 1
        if shown > 20:
            print(f"    ... and {shown - 20} more")
        print(f"  Skipped by language: {dict(sorted(skipped_by_lang.items()))}")

    return (all_files_meta, all_classes, all_functions, all_imports, all_calls,
            all_tables, all_endpoints, all_external_services, all_framework_usage,
            all_config_entries, all_scheduled_tasks, all_db_objects,
            all_sql_candidates, total_lines)


def _write_to_db(db, data: tuple, projects: list[dict], root: Path, total_files: int,
                 neo4j_pass: str, save_state: str | None = None,
                 default_schema: str | None = None, resolver_enabled: bool = True):
    """Write parsed data to Neo4j and print stats."""
    (all_files_meta, all_classes, all_functions, all_imports, all_calls,
     all_tables, all_endpoints, all_external_services, all_framework_usage,
     all_config_entries, all_scheduled_tasks, all_db_objects,
     all_sql_candidates, total_lines) = data

    project_name = root.name

    print(f"Writing to Neo4j: {len(all_classes)} classes, {len(all_functions)} functions, "
          f"{len(all_imports)} imports, {len(all_calls)} calls, {len(all_tables)} tables, "
          f"{len(all_endpoints)} endpoints, {len(all_external_services)} external services, "
          f"{len(all_framework_usage)} framework usages, {len(all_config_entries)} config entries, "
          f"{len(all_scheduled_tasks)} scheduled tasks, {len(all_db_objects)} DB objects...")

    print("  [1/14] File tree...")
    db.create_file_tree(all_files_meta)
    if all_classes:
        print(f"  [2/14] Classes ({len(all_classes)})...")
        db.create_classes(all_classes)
        print("  [3/14] Inheritance...")
        db.create_inheritance()
        print("  [4/14] External references...")
        db.create_external_references()
    else:
        print("  [2-4/14] Skipped (no classes)")
    if all_functions:
        print(f"  [5/14] Functions ({len(all_functions)})...")
        db.create_functions(all_functions)
    else:
        print("  [5/14] Skipped (no functions)")
    if all_imports:
        print(f"  [6/14] Imports ({len(all_imports)})...")
        db.create_imports(all_imports)
        db.resolve_imports()
    else:
        print("  [6/14] Skipped (no imports)")
    if all_calls:
        print(f"  [7/14] Calls ({len(all_calls)})...")
        db.create_calls(all_calls)
    else:
        print("  [7/14] Skipped (no calls)")
    if all_tables:
        print(f"  [8/14] Tables ({len(all_tables)})...")
        db.create_tables(all_tables, default_schema=default_schema)
    else:
        print("  [8/14] Skipped (no tables)")
    if all_endpoints:
        print(f"  [9/14] Endpoints ({len(all_endpoints)})...")
        db.create_endpoints(all_endpoints)
    else:
        print("  [9/14] Skipped (no endpoints)")
    if all_external_services:
        print(f"  [10/14] External services ({len(all_external_services)})...")
        db.create_external_services(all_external_services)
    else:
        print("  [10/14] Skipped (no external services)")
    if all_framework_usage:
        print(f"  [11/14] Framework usage ({len(all_framework_usage)})...")
        db.create_framework_usage(all_framework_usage)
    else:
        print("  [11/14] Skipped (no framework usage)")
    if all_config_entries:
        print(f"  [12/14] Config entries ({len(all_config_entries)})...")
        db.create_config_entries(all_config_entries)
    else:
        print("  [12/14] Skipped (no config entries)")
    if all_scheduled_tasks:
        print(f"  [13/14] Scheduled tasks ({len(all_scheduled_tasks)})...")
        db.create_scheduled_tasks(all_scheduled_tasks)
    else:
        print("  [13/14] Skipped (no scheduled tasks)")
    if all_db_objects:
        print(f"  [14/14] DB objects ({len(all_db_objects)})...")
        db.create_db_objects(all_db_objects, default_schema=default_schema)
    else:
        print("  [14/14] Skipped (no DB objects)")

    db.resolve_table_view_duplicates()
    db.refresh_global_links()

    # Code->DB inventory resolver (T2) — MATCH-only edges to existing DDL nodes.
    if resolver_enabled and all_sql_candidates:
        print(f"  Resolver: matching {len(all_sql_candidates)} SQL candidates "
              f"against DDL inventory...")
        res_stats = db.resolve_code_db_inventory(all_sql_candidates,
                                                 default_schema=default_schema)
        print(f"  Resolver: created {res_stats['edges']} edges "
              f"({res_stats['marked_dynamic']} functions marked has_dynamic_sql)")
    elif not resolver_enabled:
        print("  Resolver: disabled (--no-resolver)")

    # Create sub-project nodes
    for proj in projects:
        db.create_project(proj["name"], proj["path"], 0, 0, project_type=proj["type"])

    # Link files to projects by path prefix
    db.link_files_to_projects()

    # Remove umbrella project if sub-projects found
    if len(projects) > 1:
        db.delete_project(project_name)

    # Update stats after linking
    db.update_project_stats()

    if save_state:
        db.save_index_state(project_name, save_state)

    # Stats
    stats = db.get_stats()
    print()
    print("=" * 50)
    print("Graph built successfully!")
    print()
    print("Node counts:")
    for label, count in sorted(stats.items()):
        if label != "relationships" and count > 0:
            print(f"  {label}: {count}")
    if "relationships" in stats:
        print("Relationships:")
        for rel_type, count in stats["relationships"].items():
            print(f"  {rel_type}: {count}")
    print()
    print(f"Projects detected: {len(projects)}")
    for proj in projects:
        print(f"  {proj['name']} ({proj['type']})")
    print()
    print(f"Open Neo4j Browser: http://localhost:7474")
    print(f"Connect with: bolt://localhost:7687 (neo4j / {neo4j_pass})")
    print("=" * 50)

    db.close()


def index_project(
    project_path: str,
    neo4j_uri: str = None,
    neo4j_user: str = None,
    neo4j_pass: str = None,
    db_schema_paths: list[str] | None = None,
    default_schema: str | None = None,
    resolver_enabled: bool = True,
):
    neo4j_uri = neo4j_uri or os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    neo4j_user = neo4j_user or os.environ.get("NEO4J_USER", "neo4j")
    neo4j_pass = neo4j_pass or os.environ.get("NEO4J_PASS", "sahelper2026")
    root = Path(project_path).resolve()
    project_name = root.name

    print(f"SA-Helper Graph Indexer")
    print(f"Project: {root}")
    print(f"Neo4j:   {neo4j_uri}")
    if db_schema_paths:
        print(f"DB schemas: {', '.join(db_schema_paths)}")
    print()

    # 1. Detect sub-projects
    projects = _detect_projects(root, db_schema_paths)
    if not projects:
        projects = [{"name": project_name, "path": str(root), "root": str(root), "type": "code"}]
    print(f"Detected {len(projects)} project(s):")
    for proj in projects:
        print(f"  {proj['name']} ({proj['type']}) — {proj['path']}")
    print()

    # 2. Scan files
    print("Scanning project files...")
    files = scan(str(root))
    if not files:
        print("No parseable files found.")
        return

    detected_stack = detect_stack(str(root))
    stack_str = ", ".join(f"{lang} ({cnt})" for lang, cnt in sorted(detected_stack.items()))
    print(f"  [Stack] Detected tech stack: {stack_str or 'Unknown'}")

    lang_dist = {}
    for _, lang, _ in files:
        lang_dist[lang] = lang_dist.get(lang, 0) + 1
    for lang, count in sorted(lang_dist.items()):
        print(f"  {lang}: {count} files")
    print(f"  Total: {len(files)} files")

    # Движок индексации: запускаем Semgrep ОДИН раз по всему проекту (single pass),
    # а не на каждый файл. Находки группируются по файлам и переиспользуются воркерами.
    semgrep_ran = False
    sg_by_file = None
    if shutil.which("semgrep"):
        print("  [Engine] Running Semgrep over the whole project (single pass)...")
        _sg_indexer = SemgrepIndexer()
        sg_by_file = _sg_indexer.run_semgrep_on_project(root)
        if sg_by_file is not None:
            semgrep_ran = True
            print(f"  [Engine] Semgrep done — entities for {len(sg_by_file)} file(s). Using Semgrep engine.")
        else:
            print("  [Engine] Semgrep scan failed — falling back to Tree-sitter.")
    else:
        print("  [Engine] Semgrep not installed — using built-in Tree-sitter "
              "(install via indexer/requirements-semgrep.txt).")
    print()


    # 3. Connect to Neo4j
    print("Connecting to Neo4j...")
    db = _connect_db(neo4j_uri, neo4j_user, neo4j_pass)

    print("Connected. Clearing previous graph...")
    db.clear_graph()

    print("Creating indexes...")
    db.create_indexes()

    # 4. Parse files in parallel
    print("Parsing files...")
    file_tasks = [(abs_path, lang, rel_path) for abs_path, lang, rel_path in files]

    # 4b. Add DB schema DDL files
    if db_schema_paths:
        for schema_path in db_schema_paths:
            schema_root = Path(schema_path).resolve()
            if not schema_root.exists():
                print(f"  WARNING: DB schema path not found: {schema_root}")
                continue
            sql_files = scan(str(schema_root))
            sql_files = [(p, l, r) for p, l, r in sql_files if l == "sql_ddl"]
            if sql_files:
                print(f"  DB schema ({schema_root.name}): {len(sql_files)} SQL files")
                file_tasks.extend(sql_files)

    data = _parse_files_parallel(root, file_tasks,
                                 semgrep_ran=semgrep_ran, sg_by_file=sg_by_file)

    # 5. Resolve default schema
    if default_schema is None:
        default_schema = _detect_default_schema(data[11], data[5])
    if default_schema:
        print(f"  Default schema: {default_schema}")
    print()

    # 6. Write to Neo4j
    head_sha = get_head_commit(str(root))
    _write_to_db(db, data, projects, root, len(files), neo4j_pass,
                 save_state=head_sha, default_schema=default_schema,
                 resolver_enabled=resolver_enabled)


def index_incremental(
    project_path: str,
    neo4j_uri: str = None,
    neo4j_user: str = None,
    neo4j_pass: str = None,
    default_schema: str | None = None,
    resolver_enabled: bool = True,
):
    """Incrementally update the graph based on git diff."""
    neo4j_uri = neo4j_uri or os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    neo4j_user = neo4j_user or os.environ.get("NEO4J_USER", "neo4j")
    neo4j_pass = neo4j_pass or os.environ.get("NEO4J_PASS", "sahelper2026")
    root = Path(project_path).resolve()
    project_name = root.name

    print(f"SA-Helper Graph Indexer (incremental)")
    print(f"Project: {root}")
    print(f"Neo4j:   {neo4j_uri}")
    print()

    # 1. Check git repo
    if not is_git_repo(str(root)):
        print("Not a git repository. Falling back to full index...")
        index_project(project_path, neo4j_uri, neo4j_user, neo4j_pass,
                      default_schema=default_schema)
        return

    head_sha = get_head_commit(str(root))
    if not head_sha:
        print("Cannot determine HEAD commit. Falling back to full index...")
        index_project(project_path, neo4j_uri, neo4j_user, neo4j_pass,
                      default_schema=default_schema)
        return

    # 2. Connect and get previous state
    db = _connect_db(neo4j_uri, neo4j_user, neo4j_pass)
    prev_sha = db.get_index_state(project_name)
    db.close()

    if not prev_sha:
        print("No previous index found. Falling back to full index...")
        index_project(project_path, neo4j_uri, neo4j_user, neo4j_pass,
                      default_schema=default_schema)
        return

    print(f"Previous index: {prev_sha[:8]}")
    print(f"Current HEAD:   {head_sha[:8]}")

    if prev_sha == head_sha:
        print("No changes since last index. Nothing to do.")
        return

    # 3. Get changed files
    changed, deleted = get_changed_files(str(root), prev_sha)

    # Filter to supported files only
    changed_supported = [(p, is_supported_file(p)) for p in changed]
    changed_supported = [(p, lang) for p, lang in changed_supported if lang]
    deleted_supported = [p for p in deleted if is_supported_file(p)]

    all_diff = changed_supported + [(p, None) for p in deleted_supported]
    print(f"\nChanges: {len(changed_supported)} modified, {len(deleted_supported)} deleted")

    if not changed_supported and not deleted_supported:
        # Only unsupported files changed — just update the SHA
        db = _connect_db(neo4j_uri, neo4j_user, neo4j_pass)
        db.save_index_state(project_name, head_sha)
        db.close()
        print("No supported files changed. Updated index state.")
        return

    # 4. Safety check: if >30% of total files changed, fall back
    all_files = scan(str(root))
    if len(all_diff) > len(all_files) * 0.3:
        print(f"WARNING: {len(all_diff)} files changed (>30%). Falling back to full index...")
        index_project(project_path, neo4j_uri, neo4j_user, neo4j_pass,
                      default_schema=default_schema)
        return

    # 5. Delete old nodes for changed + deleted files
    db = _connect_db(neo4j_uri, neo4j_user, neo4j_pass)
    paths_to_delete = [p for p, _ in changed_supported] + deleted_supported
    print(f"Removing old nodes for {len(paths_to_delete)} files...")
    db.delete_file_nodes(paths_to_delete)
    db.cleanup_orphan_nodes()

    # 6. Re-parse only changed files
    print("Re-parsing changed files...")
    file_tasks = [(str(root / p), lang, p) for p, lang in changed_supported]
    data = _parse_files_parallel(root, file_tasks)

    # 7. Write new nodes + refresh global links
    _write_to_db(db, data, project_name, root, len(all_files),
                 neo4j_pass, save_state=head_sha, default_schema=default_schema,
                 resolver_enabled=resolver_enabled)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SA-Helper Graph Indexer")
    parser.add_argument("project_path", help="Path to the project to index")
    parser.add_argument("--neo4j-uri", default=None, help="Neo4j Bolt URI (env: NEO4J_URI)")
    parser.add_argument("--neo4j-user", default=None, help="Neo4j username (env: NEO4J_USER)")
    parser.add_argument("--neo4j-pass", default=None, help="Neo4j password (env: NEO4J_PASS)")
    parser.add_argument("--incremental", action="store_true",
                        help="Incremental update based on git diff (default: full rebuild)")
    parser.add_argument("--db-schema", action="append", default=[],
                        help="Additional DDL directory to scan for .sql files (repeatable)")
    parser.add_argument("--default-schema", default=None,
                        help="Default DB schema for objects without explicit schema "
                             "(e.g. 'dbo' for MS SQL, 'public' for PostgreSQL). "
                             "Auto-detected from DDL if not specified.")
    parser.add_argument("--no-resolver", dest="resolver", action="store_false",
                        default=True,
                        help="Disable the code->DB inventory resolver (T2). "
                             "With it off the graph is identical to the pre-resolver build.")

    args = parser.parse_args()
    if args.incremental:
        index_incremental(args.project_path, args.neo4j_uri, args.neo4j_user, args.neo4j_pass,
                          default_schema=args.default_schema, resolver_enabled=args.resolver)
    else:
        index_project(args.project_path, args.neo4j_uri, args.neo4j_user, args.neo4j_pass,
                      db_schema_paths=args.db_schema, default_schema=args.default_schema,
                      resolver_enabled=args.resolver)
