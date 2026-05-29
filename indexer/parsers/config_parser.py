"""Config parser — extracts DB, Redis, Sphinx, Queue infrastructure from config files."""

from __future__ import annotations

import json
import re
import configparser
from pathlib import Path
from tree_sitter import Node

from parsers.base import BaseParser

# Keys that indicate infrastructure components
INFRA_KEY_PATTERNS = {
    "db": re.compile(
        r"(?:dsn|database|db_host|db_name|db_pass|db_user|connection_string|"
        r"jdbc|mysql|pgsql|mysqli|pdo|sqlsrv|oci|db2)", re.IGNORECASE
    ),
    "redis": re.compile(r"(?:redis|cache_driver|cache_host)", re.IGNORECASE),
    "sphinx": re.compile(r"(?:sphinx|searchd|manticore)", re.IGNORECASE),
    "elasticsearch": re.compile(r"(?:elasticsearch|elastic|es_host)", re.IGNORECASE),
    "queue": re.compile(r"(?:rabbitmq|amqp|queue|beanstalk|sqs|kafka)", re.IGNORECASE),
    "cache": re.compile(r"(?:memcache|memcached|cache_host|cache_port)", re.IGNORECASE),
    "log": re.compile(r"(?:log_path|log_file|syslog|graylog|fluentd)", re.IGNORECASE),
}

# Value patterns that hint at infrastructure
INFRA_VALUE_PATTERNS = {
    "db": re.compile(
        r"(?:mysql|pgsql|sqlite|sqlsrv|oci|mongodb://|jdbc:|"
        r"host\s*=.*port\s*=|dbname\s*=|dblib)", re.IGNORECASE
    ),
    "redis": re.compile(r"redis://", re.IGNORECASE),
    "sphinx": re.compile(r"(?:sphinx|manticore|9306|9312)", re.IGNORECASE),
    "elasticsearch": re.compile(r"elasticsearch", re.IGNORECASE),
    "log": re.compile(r"(?:sentry|graylog|fluentd|logstash|datadog)", re.IGNORECASE),
    "queue": re.compile(r"(?:rabbitmq|amqp|beanstalk|sqs|kafka)", re.IGNORECASE),
}

# URL patterns that override key-based classification
URL_TYPE_OVERRIDES = [
    (re.compile(r"sentry", re.IGNORECASE), "log"),
    (re.compile(r"elasticsearch|elastic", re.IGNORECASE), "elasticsearch"),
    (re.compile(r"rabbitmq|amqp", re.IGNORECASE), "queue"),
    (re.compile(r"redis", re.IGNORECASE), "redis"),
    (re.compile(r"kafka", re.IGNORECASE), "queue"),
]


def _classify_key(key: str) -> str | None:
    for infra_type, pattern in INFRA_KEY_PATTERNS.items():
        if pattern.search(key):
            return infra_type
    return None


def _classify_value(value: str) -> str | None:
    val = str(value)
    # Check URL-based overrides first (most accurate)
    if "://" in val:
        for pattern, infra_type in URL_TYPE_OVERRIDES:
            if pattern.search(val):
                return infra_type
        # URL that doesn't match any known service — not a DB connection
        if re.match(r"https?://", val):
            return None
    # Check value patterns
    for infra_type, pattern in INFRA_VALUE_PATTERNS.items():
        if pattern.search(val):
            return infra_type
    return None


def _classify_entry(key: str, value: str) -> str | None:
    """Classify config entry: value takes priority over key."""
    val_type = _classify_value(value)
    if val_type:
        return val_type
    # Key is fallback — only trust if value is a short scalar
    val = str(value)
    if len(val) < 50 and "://" not in val:
        return _classify_key(key)
    return None


def _parse_env(text: str, file_path: str) -> list[dict]:
    results = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"^([A-Za-z_]\w*)\s*=\s*(.+)$", line)
        if not match:
            continue
        key, value = match.group(1), match.group(2).strip().strip("\"'")
        infra_type = _classify_entry(key, value)
        if infra_type:
            results.append({
                "key": key,
                "value": value,
                "type": infra_type,
                "file": file_path,
                "line": text[:text.index(line)].count("\n") + 1,
            })
    return results


def _parse_ini(text: str, file_path: str) -> list[dict]:
    results = []
    parser = configparser.ConfigParser()
    parser.read_string(text)
    for section in parser.sections():
        for key, value in parser.items(section):
            infra_type = _classify_entry(key, value)
            if infra_type:
                results.append({
                    "key": f"{section}.{key}",
                    "value": value,
                    "type": infra_type,
                    "file": file_path,
                    "line": 0,
                })
    return results


def _parse_json_config(text: str, file_path: str) -> list[dict]:
    results = []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return results

    def walk(obj, prefix=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                full_key = f"{prefix}.{k}" if prefix else k
                if isinstance(v, (dict, list)):
                    walk(v, full_key)
                elif isinstance(v, (str, int, float, bool)):
                    infra_type = _classify_entry(k, str(v))
                    if infra_type:
                        results.append({
                            "key": full_key,
                            "value": str(v),
                            "type": infra_type,
                            "file": file_path,
                            "line": 0,
                        })
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                walk(item, f"{prefix}[{i}]")

    walk(data)
    return results


def _parse_yaml_config(text: str, file_path: str) -> list[dict]:
    try:
        import yaml
    except ImportError:
        return []
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return []
    if not isinstance(data, dict):
        return []
    return _parse_json_config(json.dumps(data), file_path)


def _parse_xml_config(text: str, file_path: str) -> list[dict]:
    import xml.etree.ElementTree as ET
    results = []
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return results

    def walk(node, prefix=""):
        for attr_name, attr_value in node.attrib.items():
            infra_type = _classify_entry(attr_name, attr_value)
            if infra_type:
                full_key = f"{prefix}.{attr_name}" if prefix else attr_name
                results.append({
                    "key": full_key,
                    "value": attr_value,
                    "type": infra_type,
                    "file": file_path,
                    "line": 0,
                })
        for child in node:
            tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            walk(child, f"{prefix}.{tag}" if prefix else tag)

    walk(root)
    return results


class ConfigParser(BaseParser):
    """Lightweight parser for config files — extracts infrastructure entries."""

    language = None
    extensions = [".yml", ".yaml", ".ini", ".conf", ".env", ".xml", ".json", ".toml"]

    # Paths that should be ignored — not real infrastructure config
    IGNORED_PATH_PATTERNS = [
        "node_modules",
        "package-lock.json",
        "composer.lock",
        "vendor/",
        "/tests/",
        "/test/",
        "/__tests__/",
        "/fixtures/",
        "/fixtures.",
        ".test.",
        ".spec.",
    ]

    def __init__(self):
        pass

    def parse(self, source_code: bytes, file_path: str) -> dict:
        # Filter out non-infrastructure config files
        path_lower = file_path.lower()
        if any(p in path_lower for p in self.IGNORED_PATH_PATTERNS):
            return self._empty_result()

        text = source_code.decode("utf-8", errors="replace")
        ext = Path(file_path).suffix.lower()

        if ext in (".yml", ".yaml"):
            entries = _parse_yaml_config(text, file_path)
        elif ext in (".ini", ".conf"):
            entries = _parse_ini(text, file_path)
        elif ext == ".env":
            entries = _parse_env(text, file_path)
        elif ext == ".json":
            # Skip large JSON files (likely package-lock, composer.lock)
            if len(text) > 100_000:
                return self._empty_result()
            entries = _parse_json_config(text, file_path)
        elif ext == ".xml":
            entries = _parse_xml_config(text, file_path)
        elif ext == ".toml":
            entries = _parse_json_config(text, file_path)  # approximate
        else:
            entries = []

        return {
            "classes": [],
            "functions": [],
            "imports": [],
            "calls": [],
            "tables": [],
            "endpoints": [],
            "external_services": [],
            "framework_usage": [],
            "config_entries": entries,
            "scheduled_tasks": [],
        }

    @staticmethod
    def _empty_result():
        return {
            "classes": [],
            "functions": [],
            "imports": [],
            "calls": [],
            "tables": [],
            "endpoints": [],
            "external_services": [],
            "framework_usage": [],
            "config_entries": [],
            "scheduled_tasks": [],
        }

    def _extract_classes(self, root, file_path, source):
        return []

    def _extract_functions(self, root, file_path, source):
        return []

    def _extract_imports(self, root, file_path, source):
        return []

    def _extract_calls(self, root, file_path, source):
        return []
