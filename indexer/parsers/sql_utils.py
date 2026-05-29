"""Shared SQL extraction utilities — used by all language parsers."""

from __future__ import annotations

import re

SQL_KEYWORDS = {
    "SELECT", "FROM", "WHERE", "SET", "AND", "OR", "ON", "AS", "INTO",
    "VALUES", "UPDATE", "DELETE", "INSERT", "CREATE", "ALTER", "DROP",
    "INDEX", "TABLE", "JOIN", "LEFT", "RIGHT", "INNER", "OUTER", "CROSS",
    "GROUP", "ORDER", "BY", "HAVING", "LIMIT", "OFFSET", "UNION", "ALL",
    "DISTINCT", "NOT", "NULL", "EXISTS", "BETWEEN", "LIKE", "IN", "IS",
    "IF", "ELSE", "END", "THEN", "WHEN", "CASE", "WHILE", "FOR", "EACH",
}

SQL_FALSE_POSITIVES = {
    "PRODUCTION", "SRC", "DBO", "HIGH", "RESULT", "RESULTS", "GIVEN", "RUN",
    "QUERIES", "QUERY", "DATA", "DATABASE", "SCHEMA", "ROW", "ROWS",
    "FIELD", "FIELDS", "RECORD", "RECORDS", "VALUE", "VALUES",
    "COLUMN", "COLUMNS", "BACKUP", "TEMP", "TMP", "LOG", "LOGS",
    "CACHE", "SESSION", "CONFIG", "DEBUG", "TEST", "TESTS",
    "MAIN", "DEFAULT", "PRIMARY", "UNIQUE", "FOREIGN",
    "ARRAY", "OBJECT", "STRING", "INT", "BOOL", "FLOAT", "DOUBLE",
    "TRUE", "FALSE", "COUNT", "SUM", "AVG", "MAX", "MIN",
    "TYPE", "NAME", "STATUS", "CODE", "ERROR", "MESSAGE", "TEXT",
    "NUMBER", "DATE", "TIME", "KEY", "INDEX",
    "SEARCHD", "INDEXER", "SOURCE", "TARGET", "OUTPUT",
    "SEGMENT", "IMPORT",
}

# SQL pattern pairs — text must contain at least one pair to qualify as SQL
SQL_PAIRS = [
    (r'\bSELECT\b', r'\bFROM\b'),
    (r'\bINSERT\b', r'\bINTO\b'),
    (r'\bUPDATE\b', r'\bSET\b'),
    (r'\bDELETE\b', r'\bFROM\b'),
    (r'\bCREATE\s+TABLE\b', None),
    (r'\bALTER\s+TABLE\b', None),
    (r'\bDROP\s+TABLE\b', None),
    (r'\bTRUNCATE\s+TABLE\b', None),
]

# Regex for extracting table names from SQL
TABLE_PATTERN = re.compile(
    r"""(?:
        (?:FROM|JOIN|INTO|UPDATE|TABLE)
        \s+(?:\[\w+\]\.)?[\[`"']?(\w+)[\]`"']?
    |
        (?:INSERT\s+INTO|DELETE\s+FROM)
        \s+(?:\[\w+\]\.)?[\[`"']?(\w+)[\]`"']?
    )""",
    re.IGNORECASE | re.VERBOSE,
)


def looks_like_sql(text: str) -> bool:
    """Check if text looks like an actual SQL query (not HTML/log string)."""
    if '<' in text and '>' in text:
        return False
    for kw1, kw2 in SQL_PAIRS:
        if kw2:
            if re.search(kw1, text, re.IGNORECASE) and re.search(kw2, text, re.IGNORECASE):
                return True
        else:
            if re.search(kw1, text, re.IGNORECASE):
                return True
    return False


def is_valid_table_name(name: str) -> bool:
    """Filter out non-table names using positive pattern matching."""
    if len(name) <= 2:
        return False
    upper = name.upper()
    if upper in SQL_KEYWORDS or upper in SQL_FALSE_POSITIVES:
        return False
    if upper.startswith("PHP"):
        return False
    return bool(re.match(r'^[a-z][a-z0-9_]{2,}$', name))


def clean_concat(text: str) -> str:
    """Merge string concatenation for multi-line SQL."""
    text = re.sub(r"'\s*\.\s*'", '', text)
    text = re.sub(r'"\s*\.\s*"', '', text)
    return text


def extract_tables_from_text(
    func_text: str,
    func_name: str,
    file_path: str,
    func_start_line: int,
) -> list[dict]:
    """Extract table names from a function body text."""
    if not looks_like_sql(func_text):
        return []

    results = []
    for match in TABLE_PATTERN.finditer(func_text):
        table_name = match.group(1) or match.group(2)
        if not table_name:
            continue
        if not is_valid_table_name(table_name):
            continue

        results.append({
            "name": table_name,
            "source_file": file_path,
            "source_line": func_start_line,
            "function_name": func_name,
            "file": file_path,
            "type": "table",
        })

    return results
