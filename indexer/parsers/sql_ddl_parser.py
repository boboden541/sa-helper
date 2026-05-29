"""SQL DDL parser — extracts tables, views, stored procedures, functions from .sql files.

Regex-based parser for MS SQL Server T-SQL DDL. No tree-sitter dependency.
Follows the same pattern as ConfigParser/ScheduledParser: overrides parse() directly.
"""

from __future__ import annotations

import re
from pathlib import Path

from parsers.base import BaseParser

DEFAULT_SCHEMA = None

# --- DDL detection patterns ---

RE_CREATE_TABLE = re.compile(
    r'CREATE\s+TABLE\s+(?:\[?(\w+)\]?\.)?\[?(\w+)\]?\s*\(',
    re.IGNORECASE,
)
RE_CREATE_VIEW = re.compile(
    r'CREATE\s+(?:OR\s+ALTER\s+)?VIEW\s+(?:\[?(\w+)\]?\.)?\[?(\w+)\]?\s*(?:WITH\s+.*?\s+)?AS\s+',
    re.IGNORECASE | re.DOTALL,
)
RE_CREATE_PROC = re.compile(
    r'(?:CREATE|ALTER)\s+PROC(?:EDURE)?\s+(?:\[?(\w+)\]?\.)?\[?(\w+)\]?',
    re.IGNORECASE,
)
RE_CREATE_FUNC = re.compile(
    r'(?:CREATE|ALTER)\s+FUNCTION\s+(?:\[?(\w+)\]?\.)?\[?(\w+)\]?',
    re.IGNORECASE,
)

# --- Body extraction ---

RE_PROC_PARAMS = re.compile(
    r'(?:CREATE|ALTER)\s+PROC(?:EDURE)?\s+(?:\[?(\w+)\]?\.)?\[?(\w+)\]?\s*'
    r'((?:@\w+\s+[\w()]+(?:\s*=\s*[^,\n]+)?\s*,?\s*)*)',
    re.IGNORECASE,
)
RE_FUNC_PARAMS = re.compile(r'@(\w+)\s+([\w()]+)', re.IGNORECASE)
RE_FUNC_RETURNS = re.compile(r'RETURNS\s+(.*?)(?:\s+(?:WITH|AS|BEGIN|RETURN))', re.IGNORECASE | re.DOTALL)

# --- Dependency extraction from body ---

RE_FROM_JOIN = re.compile(
    r'(?:FROM|JOIN)\s+(?:\[?(\w+)\]?\.)?\[?(\w+)\]?',
    re.IGNORECASE,
)
RE_INSERT_INTO = re.compile(
    r'INSERT\s+(?:INTO\s+)?(?:\[?(\w+)\]?\.)?\[?(\w+)\]?',
    re.IGNORECASE,
)
RE_UPDATE = re.compile(
    r'UPDATE\s+(?:\[?(\w+)\]?\.)?\[?(\w+)\]?',
    re.IGNORECASE,
)
RE_DELETE_FROM = re.compile(
    r'DELETE\s+FROM\s+(?:\[?(\w+)\]?\.)?\[?(\w+)\]?',
    re.IGNORECASE,
)
RE_EXEC = re.compile(
    r'(?:EXEC(?:UTE)?)\s+(?:\[?(\w+)\]?\.)?\[?(\w+)\]?',
    re.IGNORECASE,
)

RE_DYNAMIC_SQL = re.compile(
    r'(?:'
    r'sp_executesql'
    r'|EXEC\s*\(\s*@'
    r'|EXECUTE\s*\(\s*@'
    r'|EXEC\s+\@\w+\s*\+'
    r'|EXEC\s+\@\w+\s+--'
    r'|\+\s*@'
    r'|\+\s*N\''
    r'|SET\s+@\w+\s*=\s*N?\'\s*(?:SELECT|INSERT|UPDATE|DELETE)'
    r')',
    re.IGNORECASE,
)

RE_SYSTEM_SP = re.compile(r'^sp_MS(?:del|upd|ins)_', re.IGNORECASE)

# SQL keywords to filter out from table name matches
SQL_NON_TABLE = {
    "SELECT", "WHERE", "SET", "AND", "OR", "ON", "AS", "INTO", "VALUES",
    "GROUP", "ORDER", "BY", "HAVING", "LIMIT", "OFFSET", "UNION", "ALL",
    "DISTINCT", "NOT", "NULL", "EXISTS", "BETWEEN", "LIKE", "IN", "IS",
    "IF", "ELSE", "END", "THEN", "WHEN", "CASE", "WHILE", "FOR", "EACH",
    "BEGIN", "RETURN", "DECLARE", "NOLOCK", "WITH", "TOP", "OUTPUT",
    "INNER", "LEFT", "RIGHT", "OUTER", "CROSS", "FULL", "JOIN", "APPLY",
    "OVER", "PARTITION", "ROW_NUMBER", "CAST", "CONVERT", "COALESCE",
    "ISNULL", "GETDATE", "SCOPE_IDENTITY", "NEWID", "BIT", "INT",
    "VARCHAR", "NVARCHAR", "DATETIME", "FLOAT", "DECIMAL", "TEXT",
    "CHAR", "BIGINT", "SMALLINT", "TINYINT", "NUMERIC", "MONEY",
    "TABLE", "VIEW", "PROC", "PROCEDURE", "FUNCTION", "TRIGGER",
    "INDEX", "CURSOR", "FETCH", "NEXT", "OPEN", "CLOSE", "DEALLOCATE",
    "TRY", "CATCH", "THROW", "RAISERROR", "PRINT", "EXEC", "EXECUTE",
    "MERGE", "USING", "MATCHED", "WHEN", "THEN",
}

# Column definition pattern for CREATE TABLE
RE_COLUMN_DEF = re.compile(
    r'\[?(\w+)\]?\s+([\w]+(?:\s*\([^)]+\))?)\s*(?:(?:NOT\s+)?NULL)?',
    re.IGNORECASE,
)


def _strip_comments(text: str) -> str:
    """Remove SQL comments."""
    text = re.sub(r'--[^\n]*', '', text)
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)
    return text


def _normalize_name(schema: str | None, name: str) -> tuple[str, str]:
    """Normalize schema.name, defaulting to dbo."""
    name = name.strip('[]')
    schema = schema.strip('[]') if schema else DEFAULT_SCHEMA
    return schema, name


def _split_batches(text: str) -> list[str]:
    """Split SQL text by GO separators."""
    return re.split(r'^\s*GO\s*$', text, flags=re.MULTILINE | re.IGNORECASE)


def _is_valid_db_name(name: str) -> bool:
    """Filter out SQL keywords and short names."""
    if len(name) <= 2:
        return False
    return name.upper() not in SQL_NON_TABLE


def _extract_columns(create_body: str) -> list[dict]:
    """Extract column definitions from CREATE TABLE body (between first ( and matching )."""
    # Get content between first ( and its matching )
    depth = 0
    start = None
    for i, ch in enumerate(create_body):
        if ch == '(':
            if start is None:
                start = i + 1
            depth += 1
        elif ch == ')':
            depth -= 1
            if depth == 0 and start is not None:
                body = create_body[start:i]
                break
    else:
        return []

    columns = []
    for part in body.split(','):
        part = part.strip()
        if not part:
            continue
        # Skip constraints
        upper = part.upper()
        if upper.startswith(('CONSTRAINT', 'PRIMARY KEY', 'UNIQUE', 'CHECK', 'FOREIGN', 'INDEX', 'KEY')):
            continue
        match = RE_COLUMN_DEF.match(part)
        if match:
            col_name = match.group(1)
            col_type = match.group(2)
            nullable = 'NOT NULL' not in upper[len(col_name):]
            if col_name.upper() not in SQL_NON_TABLE:
                columns.append({
                    "name": col_name,
                    "type": col_type,
                    "nullable": nullable,
                })
    return columns


def _extract_dependencies(body: str, src_schema: str, src_name: str, source_label: str | None = None, has_dynamic_sql: bool = False) -> list[dict]:
    """Extract DB dependencies from SP/Function/View body.

    When source_label is "View", FROM/JOIN produces DEPENDS_ON instead of QUERIES,
    since views depend on their underlying tables/views but don't "query" them actively.
    """
    deps = []
    seen = set()

    def _add(schema, name, rel):
        s, n = _normalize_name(schema, name)
        if not _is_valid_db_name(n):
            return
        # Views use DEPENDS_ON for read access (FROM/JOIN)
        if source_label == "View" and rel == "QUERIES":
            rel = "DEPENDS_ON"
        key = (s, n, rel)
        if key not in seen and (s, n) != (src_schema, src_name):
            seen.add(key)
            deps.append({"target_schema": s, "target_name": n, "rel": rel})

    for m in RE_FROM_JOIN.finditer(body):
        _add(m.group(1), m.group(2), "QUERIES")

    for m in RE_INSERT_INTO.finditer(body):
        _add(m.group(1), m.group(2), "INSERTS_INTO")

    for m in RE_UPDATE.finditer(body):
        # Skip UPDATE in SET clauses (e.g., "SET col = UPDATE...")
        context_before = body[max(0, m.start() - 20):m.start()].upper()
        if 'SET' in context_before and '=' in context_before:
            continue
        _add(m.group(1), m.group(2), "UPDATES")

    for m in RE_DELETE_FROM.finditer(body):
        _add(m.group(1), m.group(2), "DELETES_FROM")

    for m in RE_EXEC.finditer(body):
        _add(m.group(1), m.group(2), "CALLS_SP")

    # Extract from string literals in dynamic SQL
    if has_dynamic_sql:
        string_literals = re.findall(r"N?'([^']*(?:SELECT|FROM|JOIN|INSERT|UPDATE)[^']*)'", body, re.IGNORECASE)
        for lit in string_literals:
            for m in RE_FROM_JOIN.finditer(lit):
                _add(m.group(1), m.group(2), "QUERIES")
            for m in RE_INSERT_INTO.finditer(lit):
                _add(m.group(1), m.group(2), "INSERTS_INTO")
            for m in RE_UPDATE.finditer(lit):
                _add(m.group(1), m.group(2), "UPDATES")

    return deps


def _parse_params(params_str: str) -> list[dict]:
    """Parse stored procedure parameters."""
    params = []
    for m in RE_FUNC_PARAMS.finditer(params_str):
        params.append({"name": m.group(1), "type": m.group(2), "direction": "IN"})
    return params


def _try_decode(source: bytes) -> str:
    """Decode SQL source, trying UTF-8 first, then Windows-1251."""
    try:
        return source.decode('utf-8')
    except UnicodeDecodeError:
        return source.decode('windows-1251', errors='replace')


class SQLDDLParser(BaseParser):
    """Regex-based parser for SQL DDL files (MS SQL Server T-SQL)."""

    language = None
    extensions = [".sql"]

    def __init__(self):
        pass

    def parse(self, source_code: bytes, file_path: str) -> dict:
        text = _try_decode(source_code)
        text = _strip_comments(text)
        batches = _split_batches(text)

        tables = []
        db_objects = []

        for batch in batches:
            batch = batch.strip()
            if not batch:
                continue

            line_offset = text[:text.index(batch)].count("\n") + 1 if batch in text else 0

            self._parse_create_table(batch, file_path, line_offset, tables)
            self._parse_create_view(batch, file_path, line_offset, db_objects)
            self._parse_create_proc(batch, file_path, line_offset, db_objects)
            self._parse_create_func(batch, file_path, line_offset, db_objects)

        return {
            "classes": [],
            "functions": [],
            "imports": [],
            "calls": [],
            "tables": tables,
            "endpoints": [],
            "external_services": [],
            "framework_usage": [],
            "config_entries": [],
            "scheduled_tasks": [],
            "db_objects": db_objects,
        }

    def _parse_create_table(self, batch: str, file_path: str, line_offset: int, tables: list):
        for m in RE_CREATE_TABLE.finditer(batch):
            schema, name = _normalize_name(m.group(1), m.group(2))
            if not _is_valid_db_name(name):
                continue
            columns = _extract_columns(batch[m.end() - 1:])
            line_no = batch[:m.start()].count("\n") + line_offset
            tables.append({
                "name": name,
                "schema": schema,
                "type": "table",
                "columns": columns,
                "source_file": file_path,
                "source_line": line_no,
                "file": file_path,
            })

    def _parse_create_view(self, batch: str, file_path: str, line_offset: int, db_objects: list):
        for m in RE_CREATE_VIEW.finditer(batch):
            schema, name = _normalize_name(m.group(1), m.group(2))
            if not _is_valid_db_name(name):
                continue
            body = batch[m.end():]
            line_no = batch[:m.start()].count("\n") + line_offset
            deps = _extract_dependencies(body, schema, name, source_label="View")
            db_objects.append({
                "label": "View",
                "name": name,
                "schema": schema,
                "body_sql": body[:2000],
                "source_file": file_path,
                "source_line": line_no,
                "dependencies": deps,
            })

    def _parse_create_proc(self, batch: str, file_path: str, line_offset: int, db_objects: list):
        for m in RE_CREATE_PROC.finditer(batch):
            schema, name = _normalize_name(m.group(1), m.group(2))
            if not _is_valid_db_name(name):
                continue
            line_no = batch[:m.start()].count("\n") + line_offset

            # Extract parameters
            params = []
            pm = RE_PROC_PARAMS.match(batch[m.start():])
            if pm and pm.group(3):
                params = _parse_params(pm.group(3))

            # Find AS keyword followed by newline or BEGIN (body start)
            rest = batch[m.end():]
            as_match = re.search(r'\bAS\b\s*(?:\n|BEGIN\b)', rest, re.IGNORECASE)
            if as_match:
                body = rest[as_match.end():]
                body = body.lstrip()
            else:
                body = rest

            # Detect dynamic SQL patterns
            has_dynamic_sql = bool(RE_DYNAMIC_SQL.search(body))

            # Detect empty body
            is_empty = bool(re.match(
                r'\s*(?:SET\s+NOCOUNT\s+ON\s*)?(?:RETURN\s+\d?\s*)?$',
                body.strip(),
                re.IGNORECASE,
            ))

            # Detect system replication SP
            is_system = bool(RE_SYSTEM_SP.match(name))

            deps = _extract_dependencies(body, schema, name, has_dynamic_sql=has_dynamic_sql)
            db_objects.append({
                "label": "StoredProcedure",
                "name": name,
                "schema": schema,
                "parameters": params,
                "has_dynamic_sql": has_dynamic_sql,
                "is_empty": is_empty,
                "is_system": is_system,
                "is_empty": is_empty,
                "source_file": file_path,
                "source_line": line_no,
                "dependencies": deps,
            })

    def _parse_create_func(self, batch: str, file_path: str, line_offset: int, db_objects: list):
        for m in RE_CREATE_FUNC.finditer(batch):
            schema, name = _normalize_name(m.group(1), m.group(2))
            if not _is_valid_db_name(name):
                continue
            line_no = batch[:m.start()].count("\n") + line_offset

            rest = batch[m.end():]

            # Extract parameters (inside parentheses after name)
            params = []
            paren_match = re.match(r'\s*\((.*?)\)', rest, re.DOTALL)
            if paren_match:
                params = _parse_params(paren_match.group(1))

            # Extract return type
            return_type = None
            rm = RE_FUNC_RETURNS.search(rest)
            if rm:
                return_type = rm.group(1).strip()

            # Body starts after AS or BEGIN
            body_start = re.search(r'\bAS\b|\bBEGIN\b', rest, re.IGNORECASE)
            body = rest[body_start.end():] if body_start else rest[200:]
            deps = _extract_dependencies(body, schema, name)

            db_objects.append({
                "label": "DatabaseFunction",
                "name": name,
                "schema": schema,
                "parameters": params,
                "return_type": return_type,
                "source_file": file_path,
                "source_line": line_no,
                "dependencies": deps,
            })

    # Required abstract methods (unused for this parser)
    def _extract_classes(self, root, file_path, source):
        return []

    def _extract_functions(self, root, file_path, source):
        return []

    def _extract_imports(self, root, file_path, source):
        return []

    def _extract_calls(self, root, file_path, source):
        return []
