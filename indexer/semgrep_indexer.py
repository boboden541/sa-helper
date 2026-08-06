"""Semgrep Indexer Adapter — executes Semgrep CLI or native AST pattern matcher to index project graph."""

from __future__ import annotations

import os
import sys
import re
import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Список исключаемых каталогов берём из scanner.py, чтобы semgrep сканировал
# ровно то, что индексатор реально обрабатывает (без .venv/node_modules/build и т.п.).
try:
    from scanner import IGNORED_DIRS as _SCANNER_IGNORED_DIRS
except ImportError:
    _SCANNER_IGNORED_DIRS = set()

try:
    import tree_sitter
    from tree_sitter import Language, Parser, QueryCursor
    import tree_sitter_python as tspython
    import tree_sitter_javascript as tsjs
    import tree_sitter_java as tsjava
    import tree_sitter_php as tsphp
    import tree_sitter_go as tsgo
    HAS_TREE_SITTER = True
except ImportError:
    HAS_TREE_SITTER = False


TS_PATTERNS = {
    "python": {
        "classes": "(class_definition name: (identifier) @name)",
        "functions": "(function_definition name: (identifier) @name)",
        "endpoints": "(decorator (call function: (attribute attribute: (identifier)) arguments: (argument_list (string) @route)))",
    },
    "java": {
        "classes": """
            [
              (class_declaration name: (identifier) @name)
              (interface_declaration name: (identifier) @name)
              (enum_declaration name: (identifier) @name)
            ]
        """,
        "functions": """
            [
              (method_declaration name: (identifier) @name)
              (constructor_declaration name: (identifier) @name)
            ]
        """,
        "endpoints": """
            (method_declaration
              (modifiers
                [
                  (marker_annotation name: (identifier) @ann)
                  (annotation name: (identifier) @ann)
                ])
              name: (identifier) @handler)
        """,
    },
    "javascript": {
        "classes": "(class_declaration name: (identifier) @name)",
        "functions": """
            [
              (function_declaration name: (identifier) @name)
              (method_definition name: (property_identifier) @name)
            ]
        """,
        "endpoints": """
            (call_expression
              function: (member_expression property: (property_identifier) @method)
              arguments: (arguments (string) @route))
        """,
    },
    "php": {
        "classes": "(class_declaration name: (name) @name)",
        "functions": """
            [
              (method_declaration name: (name) @name)
              (function_definition name: (name) @name)
            ]
        """,
        "endpoints": """
            (scoped_call_expression
              scope: (name) @scope
              name: (name) @method
              arguments: (arguments (string) @route))
        """,
    },
}


# Reserved SQL keywords to ignore when matching table names
SQL_KEYWORDS = {
    "SELECT", "FROM", "WHERE", "JOIN", "LEFT", "RIGHT", "INNER", "OUTER", "ON",
    "AND", "OR", "GROUP", "BY", "ORDER", "HAVING", "LIMIT", "OFFSET", "AS",
    "INSERT", "INTO", "VALUES", "UPDATE", "SET", "DELETE", "TRUNCATE", "TABLE",
    "DATABASE", "CREATE", "ALTER", "DROP", "NULL", "NOT", "IN", "IS", "EXISTS",
    "DUAL", "EXEC", "EXECUTE", "dbo", "sys", "INFORMATION_SCHEMA", "WITH", "UNION",
}


class SemgrepIndexer:
    """Adapter for running Semgrep CLI or native AST queries and transforming findings into Neo4j graph nodes."""

    def __init__(self, rules_dir: str | None = None):
        if rules_dir is None:
            rules_dir = str(Path(__file__).parent / "semgrep_rules")
        self.rules_dir = rules_dir
        self.semgrep_bin = shutil.which("semgrep")

        self._ts_languages = {}
        self._ts_parsers = {}
        self._ts_compiled = {}

        if HAS_TREE_SITTER:
            self._ts_languages = {
                "python": Language(tspython.language()),
                "javascript": Language(tsjs.language()),
                "java": Language(tsjava.language()),
                "php": Language(tsphp.language_php()),
                "go": Language(tsgo.language()),
            }
            self._ts_parsers = {lang: Parser(l_obj) for lang, l_obj in self._ts_languages.items()}

            for lang, queries in TS_PATTERNS.items():
                if lang not in self._ts_languages:
                    continue
                self._ts_compiled[lang] = {}
                l_obj = self._ts_languages[lang]
                for q_type, q_str in queries.items():
                    try:
                        self._ts_compiled[lang][q_type] = tree_sitter.Query(l_obj, q_str)
                    except Exception:
                        pass

    def parse_sql_ddl(self, abs_path: str, rel_path: str) -> dict:
        """Parse MSSQL / PostgreSQL / MySQL DDL statements from .sql files."""
        try:
            with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except OSError:
            return {"tables": [], "db_objects": []}

        tables = []
        db_objects = []

        # 1. CREATE TABLE
        for m in re.finditer(r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:\[?(\w+)\]?\.)?\[?(\w+)\]?', content, re.IGNORECASE):
            schema = m.group(1) or 'dbo'
            tbl_name = m.group(2)
            if tbl_name.upper() in SQL_KEYWORDS:
                continue
            line = content[:m.start()].count('\n') + 1
            tables.append({
                'name': tbl_name,
                'table_name': tbl_name,
                'schema': schema,
                'type': 'table',
                'source_file': rel_path,
                'source_line': line,
                'file': rel_path,
                'line': line,
            })

        # 2. CREATE VIEW
        for m in re.finditer(r'CREATE\s+VIEW\s+(?:\[?(\w+)\]?\.)?\[?(\w+)\]?', content, re.IGNORECASE):
            schema = m.group(1) or 'dbo'
            view_name = m.group(2)
            line = content[:m.start()].count('\n') + 1
            db_objects.append({
                'label': 'View',
                'schema': schema,
                'name': view_name,
                'source_file': rel_path,
                'source_line': line,
            })

        # 3. CREATE PROCEDURE
        for m in re.finditer(r'CREATE\s+(?:OR\s+REPLACE\s+)?PROC(?:EDURE)?\s+(?:\[?(\w+)\]?\.)?\[?(\w+)\]?', content, re.IGNORECASE):
            schema = m.group(1) or 'dbo'
            proc_name = m.group(2)
            line = content[:m.start()].count('\n') + 1
            db_objects.append({
                'label': 'StoredProcedure',
                'schema': schema,
                'name': proc_name,
                'source_file': rel_path,
                'source_line': line,
            })

        # 4. CREATE FUNCTION
        for m in re.finditer(r'CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+(?:\[?(\w+)\]?\.)?\[?(\w+)\]?', content, re.IGNORECASE):
            schema = m.group(1) or 'dbo'
            func_name = m.group(2)
            line = content[:m.start()].count('\n') + 1
            db_objects.append({
                'label': 'DatabaseFunction',
                'schema': schema,
                'name': func_name,
                'source_file': rel_path,
                'source_line': line,
            })

        return {"tables": tables, "db_objects": db_objects}

    def parse_code_file_relationships(self, abs_path: str, lang: str, rel_path: str) -> dict:
        """Extract imports, embedded SQL queries, and HTTP REST calls from code files."""
        try:
            with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except OSError:
            return {"imports": [], "tables": [], "db_objects": [], "calls": [], "external_services": []}

        imports = []
        tables = []
        db_objects = []
        calls = []
        services = []

        # 1. IMPORTS
        # PHP use / require / include
        if lang == "php":
            for m in re.finditer(r'(?:use|require|require_once|include|include_once)\s+[\'"]?([^\s;\'"]+)', content):
                line = content[:m.start()].count('\n') + 1
                imports.append({
                    "file": rel_path,
                    "rel_path": rel_path,
                    "source": m.group(1),
                    "aliases": [],
                    "line": line,
                })
        # Python import / from
        elif lang == "python":
            for m in re.finditer(r'(?:from|import)\s+([\w\.]+)', content):
                line = content[:m.start()].count('\n') + 1
                imports.append({
                    "file": rel_path,
                    "rel_path": rel_path,
                    "source": m.group(1),
                    "aliases": [],
                    "line": line,
                })
        # Java import
        elif lang == "java":
            for m in re.finditer(r'import\s+([\w\.\*]+);', content):
                line = content[:m.start()].count('\n') + 1
                imports.append({
                    "file": rel_path,
                    "rel_path": rel_path,
                    "source": m.group(1),
                    "aliases": [],
                    "line": line,
                })
        # JS/TS import / require
        elif lang in ("javascript", "typescript"):
            for m in re.finditer(r'(?:import|require)\s*\(?[\'"]([^\'\"]+)[\'"]', content):
                line = content[:m.start()].count('\n') + 1
                imports.append({
                    "file": rel_path,
                    "rel_path": rel_path,
                    "source": m.group(1),
                    "aliases": [],
                    "line": line,
                })


        # 2. SQL QUERIES IN CODE (SELECT / INSERT / UPDATE / DELETE / EXEC)
        # Match table queries: FROM/JOIN/INTO/UPDATE [schema.]table
        for m in re.finditer(r'(?:FROM|INTO|UPDATE|JOIN)\s+(?:\[?(\w+)\]?\.)?\[?(\w+)\]?', content, re.IGNORECASE):
            schema = m.group(1) or 'dbo'
            tbl_name = m.group(2)
            if not tbl_name or tbl_name.upper() in SQL_KEYWORDS:
                continue
            line = content[:m.start()].count('\n') + 1
            op = "SELECT"
            before = content[max(0, m.start() - 30):m.start()].upper()
            if "INSERT" in before:
                op = "INSERT"
            elif "UPDATE" in before:
                op = "UPDATE"
            elif "DELETE" in before:
                op = "DELETE"

            tables.append({
                'name': tbl_name,
                'table_name': tbl_name,
                'schema': schema,
                'type': 'table',
                'source_file': rel_path,
                'source_line': line,
                'file': rel_path,
                'line': line,
                'function_name': None,
                'operation': op,
            })

        # Match Stored Procedure executions: EXEC [schema.]sp_name
        for m in re.finditer(r'EXEC(?:UTE)?\s+(?:\[?(\w+)\]?\.)?\[?(\w+)\]?', content, re.IGNORECASE):
            schema = m.group(1) or 'dbo'
            proc_name = m.group(2)
            if not proc_name or proc_name.upper() in SQL_KEYWORDS:
                continue
            line = content[:m.start()].count('\n') + 1
            db_objects.append({
                'label': 'StoredProcedure',
                'schema': schema,
                'name': proc_name,
                'source_file': rel_path,
                'source_line': line,
            })

        # 3. HTTP / REST CLIENT CALLS
        # Extract URLs (http://... or /api/...)
        for m in re.finditer(r'[\'"](https?://[^\s\'"<>]+|/(?:api|v1|v2|service)/[^\s\'"<>]+)[\'"]', content):
            url = m.group(1)
            line = content[:m.start()].count('\n') + 1
            method = "GET"
            before = content[max(0, m.start() - 40):m.start()].upper()
            if "POST" in before:
                method = "POST"
            elif "PUT" in before:
                method = "PUT"
            elif "DELETE" in before:
                method = "DELETE"

            serv_name = url.split('/')[2] if url.startswith('http') else url.split('/')[1]
            services.append({
                "source_file": rel_path,
                "source_line": line,
                "service_name": serv_name,
                "service_type": "http",
                "url": url,
                "http_method": method,
                "caller_function": None,
            })
            calls.append({
                "caller_file": rel_path,
                "caller_func": None,
                "callee_name": url,
                "line": line,
            })

        return {
            "imports": imports,
            "tables": tables,
            "db_objects": db_objects,
            "calls": calls,
            "external_services": services,
        }

    def run_semgrep_cli(self, project_path: str) -> dict | None:
        """Run Semgrep CLI scan and return JSON output dict."""
        if not self.semgrep_bin or not os.path.exists(self.rules_dir):
            return None

        cmd = [
            self.semgrep_bin,
            "scan",
            "--config", self.rules_dir,
            "--json",
            "--quiet",
            project_path,
        ]

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if proc.returncode in (0, 1) and proc.stdout:
                return json.loads(proc.stdout)
        except Exception as e:
            print(f"Semgrep CLI execution error: {e}")
        return None

    def run_semgrep_on_project(self, root) -> dict | None:
        """Запускает Semgrep ОДИН раз по всему проекту (single pass) и группирует
        находки по файлам. Возвращает {rel_path: {classes, functions, endpoints, tables}}
        или None, если Semgrep недоступен / упал."""
        if not self.semgrep_bin or not os.path.exists(self.rules_dir):
            return None
        # Ограничиваем область semgrep тем же набором файлов, что берёт индексатор:
        # исключаем зависимые/мусорные каталоги (как scanner.py) и SQL-дампы
        # (их парсит быстрый DDL-парсер, правил для SQL в semgrep нет).
        cmd = [self.semgrep_bin, "scan", "--config", self.rules_dir, "--json", "--quiet"]
        for _ex in list(_SCANNER_IGNORED_DIRS) + ["*.sql"]:
            cmd += ["--exclude", str(_ex)]
        cmd.append(str(root))
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        except subprocess.TimeoutExpired:
            print("  [Engine] Semgrep scan timed out — falling back to Tree-sitter.")
            return None
        except Exception as e:
            print(f"  [Engine] Semgrep scan error: {e} — falling back to Tree-sitter.")
            return None
        # semgrep может выйти с code 2 (например, при ошибке в одном из правил),
        # но при этом всё равно отдать валидный JSON с находками по остальным правилам.
        # Поэтому опираемся на наличие stdout и его парсимость, а не на return code.
        if not proc.stdout:
            return None
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return None
        return self._group_semgrep_by_file(data, root)

    def _group_semgrep_by_file(self, data: dict, root) -> dict:
        """Группирует JSON-находки Semgrep по файлам: rel_path -> {classes, functions, endpoints, tables}."""
        root_path = Path(str(root)).resolve()
        grouped: dict[str, dict] = {}
        for match in data.get("results", []):
            raw_path = match.get("path", "")
            try:
                rel_path = str(Path(raw_path).relative_to(root_path))
            except ValueError:
                rel_path = raw_path
            rel_path = os.path.normpath(rel_path)

            start_line = match.get("start", {}).get("line", 1)
            end_line = match.get("end", {}).get("line", start_line)
            extra = match.get("extra", {})
            metadata = extra.get("metadata", {})
            entity_type = metadata.get("entity_type", "")
            metavars = extra.get("metavars", {})
            name = (metavars.get("$NAME", {}).get("abstract_content", "")
                    or metavars.get("$METHOD", {}).get("abstract_content", "")
                    or "Unnamed")

            bucket = grouped.setdefault(
                rel_path, {"classes": [], "functions": [], "endpoints": [], "tables": []})

            if entity_type == "class":
                bucket["classes"].append({
                    "name": name, "file": rel_path, "rel_path": rel_path,
                    "line": start_line, "line_start": start_line, "line_end": end_line,
                    "parent_class": None, "interfaces": [],
                })
            elif entity_type == "function":
                bucket["functions"].append({
                    "name": name, "file": rel_path, "rel_path": rel_path,
                    "line": start_line, "line_start": start_line, "line_end": end_line,
                    "class_name": None, "parameters": "",
                    "is_method": False, "is_entry_point": False,
                })
            elif entity_type == "endpoint":
                route = metavars.get("$ROUTE", {}).get("abstract_content", "").strip("'\" ") or "/api"
                http_method = metadata.get("http_method", "GET")
                bucket["endpoints"].append({
                    "name": f"{http_method} {route}", "type": "http", "path": route,
                    "route": route, "http_method": http_method,
                    "handler_method": name, "handler_func": name, "handler_class": None,
                    "file": rel_path, "rel_path": rel_path, "line": start_line,
                })
            elif entity_type == "table":
                bucket["tables"].append({
                    "name": name, "table_name": name, "schema": None, "type": "table",
                    "operation": "SELECT", "file": rel_path, "rel_path": rel_path,
                    "line": start_line, "source_file": rel_path,
                    "source_line": start_line, "function_name": None,
                })
        return grouped

    def run_native_tree_sitter(self, files: List[Tuple[str, str, str]]) -> Dict[str, List[Dict[str, Any]]]:
        """Native Tree-sitter query fallback for environments without Semgrep CLI."""
        res = {
            "classes": [],
            "functions": [],
            "imports": [],
            "calls": [],
            "tables": [],
            "endpoints": [],
            "external_services": [],
            "framework_usage": [],
            "db_objects": [],
        }

        parsers = self._ts_parsers
        compiled = self._ts_compiled

        for abs_path, lang, rel_path in files:
            if lang == "sql_ddl" or rel_path.endswith(".sql"):
                sql_res = self.parse_sql_ddl(abs_path, rel_path)
                res["tables"].extend(sql_res.get("tables", []))
                res["db_objects"].extend(sql_res.get("db_objects", []))
                continue

            # Extract imports, embedded SQL queries, and HTTP REST calls from code
            code_rels = self.parse_code_file_relationships(abs_path, lang, rel_path)
            res["imports"].extend(code_rels.get("imports", []))
            res["tables"].extend(code_rels.get("tables", []))
            res["db_objects"].extend(code_rels.get("db_objects", []))
            res["calls"].extend(code_rels.get("calls", []))
            res["external_services"].extend(code_rels.get("external_services", []))

            if lang not in parsers or lang not in compiled:
                continue
            try:
                with open(abs_path, "rb") as f:
                    source = f.read()
                tree = parsers[lang].parse(source)
                root = tree.root_node
                lang_q = compiled[lang]

                for q_type, q_obj in lang_q.items():
                    qc = QueryCursor(q_obj)
                    captures = qc.captures(root)
                    for capture_name, nodes in captures.items():
                        for node in nodes:
                            name_text = source[node.start_byte:node.end_byte].decode("utf-8", errors="ignore").strip("'\" ")
                            start_line = node.start_point[0] + 1
                            end_line = node.end_point[0] + 1

                            if q_type == "classes" and name_text:
                                res["classes"].append({
                                    "name": name_text,
                                    "file": rel_path,
                                    "rel_path": rel_path,
                                    "line": start_line,
                                    "line_start": start_line,
                                    "line_end": end_line,
                                    "parent_class": None,
                                    "interfaces": [],
                                })
                            elif q_type == "functions" and name_text:
                                res["functions"].append({
                                    "name": name_text,
                                    "file": rel_path,
                                    "rel_path": rel_path,
                                    "line": start_line,
                                    "line_start": start_line,
                                    "line_end": end_line,
                                    "class_name": None,
                                    "parameters": "",
                                    "is_method": False,
                                    "is_entry_point": False,
                                })
                            elif q_type == "endpoints" and name_text:
                                ep_name = f"GET {name_text}"
                                res["endpoints"].append({
                                    "name": ep_name,
                                    "type": "http",
                                    "path": name_text,
                                    "route": name_text,
                                    "http_method": "GET",
                                    "handler_method": name_text,
                                    "handler_func": name_text,
                                    "handler_class": None,
                                    "file": rel_path,
                                    "rel_path": rel_path,
                                    "line": start_line,
                                })

            except Exception:
                continue

        return res

    def process(self, project_path: str, files: List[Tuple[str, str, str]]) -> Dict[str, List[Dict[str, Any]]]:
        """Main entry point: runs Semgrep CLI or tree-sitter fallback and returns unified dictionary."""
        # For SQL files, run DDL parser directly
        has_sql = any(f[1] == "sql_ddl" or f[2].endswith(".sql") for f in files)
        if has_sql and len(files) == 1 and (files[0][1] == "sql_ddl" or files[0][2].endswith(".sql")):
            sql_res = self.parse_sql_ddl(files[0][0], files[0][2])
            return {
                "classes": [], "functions": [], "imports": [], "calls": [],
                "tables": sql_res.get("tables", []),
                "endpoints": [], "external_services": [], "framework_usage": [],
                "db_objects": sql_res.get("db_objects", []),
            }

        cli_result = self.run_semgrep_cli(project_path)
        if cli_result and "results" in cli_result:
            parsed = self._parse_semgrep_json(cli_result, project_path)
            for abs_p, l, rel_p in files:
                if l == "sql_ddl" or rel_p.endswith(".sql"):
                    sql_res = self.parse_sql_ddl(abs_p, rel_p)
                    parsed["tables"].extend(sql_res.get("tables", []))
                    parsed["db_objects"].extend(sql_res.get("db_objects", []))
                else:
                    code_rels = self.parse_code_file_relationships(abs_p, l, rel_p)
                    parsed["imports"].extend(code_rels.get("imports", []))
                    parsed["tables"].extend(code_rels.get("tables", []))
                    parsed["db_objects"].extend(code_rels.get("db_objects", []))
                    parsed["calls"].extend(code_rels.get("calls", []))
                    parsed["external_services"].extend(code_rels.get("external_services", []))
            return parsed

        # Fallback to native AST parser
        return self.run_native_tree_sitter(files)

    def _parse_semgrep_json(self, data: dict, project_path: str) -> Dict[str, List[Dict[str, Any]]]:
        """Convert Semgrep JSON findings into Neo4j graph payload."""
        root = Path(project_path).resolve()
        res = {
            "classes": [],
            "functions": [],
            "imports": [],
            "calls": [],
            "tables": [],
            "endpoints": [],
            "external_services": [],
            "framework_usage": [],
            "db_objects": [],
        }

        for match in data.get("results", []):
            raw_path = match.get("path", "")
            try:
                rel_path = str(Path(raw_path).relative_to(root))
            except ValueError:
                rel_path = raw_path

            start_line = match.get("start", {}).get("line", 1)
            end_line = match.get("end", {}).get("line", start_line)
            extra = match.get("extra", {})
            metadata = extra.get("metadata", {})
            entity_type = metadata.get("entity_type", "")

            metavars = extra.get("metavars", {})
            name = metavars.get("$NAME", {}).get("abstract_content", "") or metavars.get("$METHOD", {}).get("abstract_content", "") or "Unnamed"

            if entity_type == "class":
                res["classes"].append({
                    "name": name,
                    "file": rel_path,
                    "rel_path": rel_path,
                    "line": start_line,
                    "line_start": start_line,
                    "line_end": end_line,
                    "parent_class": None,
                    "interfaces": [],
                })
            elif entity_type == "function":
                res["functions"].append({
                    "name": name,
                    "file": rel_path,
                    "rel_path": rel_path,
                    "line": start_line,
                    "line_start": start_line,
                    "line_end": end_line,
                    "class_name": None,
                    "parameters": "",
                    "is_method": False,
                    "is_entry_point": False,
                })
            elif entity_type == "endpoint":
                route = metavars.get("$ROUTE", {}).get("abstract_content", "").strip("'\" ") or "/api"
                http_method = metadata.get("http_method", "GET")
                ep_name = f"{http_method} {route}"
                res["endpoints"].append({
                    "name": ep_name,
                    "type": "http",
                    "path": route,
                    "route": route,
                    "http_method": http_method,
                    "handler_method": name,
                    "handler_func": name,
                    "handler_class": None,
                    "file": rel_path,
                    "rel_path": rel_path,
                    "line": start_line,
                })
            elif entity_type == "table":
                res["tables"].append({
                    "name": name,
                    "table_name": name,
                    "schema": None,
                    "type": "table",
                    "operation": "SELECT",
                    "file": rel_path,
                    "rel_path": rel_path,
                    "line": start_line,
                    "source_file": rel_path,
                    "source_line": start_line,
                    "function_name": None,
                })

        return res
