"""Parser registry — maps language names to parser classes."""

from __future__ import annotations

from parsers.base import BaseParser


def _lazy_import(module_name: str, class_name: str):
    def factory():
        import importlib
        mod = importlib.import_module(f"parsers.{module_name}")
        return getattr(mod, class_name)()
    return factory


REGISTRY: dict[str, callable] = {
    "python": _lazy_import("python_parser", "PythonParser"),
    "javascript": _lazy_import("js_parser", "JSParser"),
    "java": _lazy_import("java_parser", "JavaParser"),
    "php": _lazy_import("php_parser", "PHPParser"),
    "go": _lazy_import("go_parser", "GoParser"),
    "config": _lazy_import("config_parser", "ConfigParser"),
    "cron": _lazy_import("scheduled_parser", "ScheduledParser"),
    "sql_ddl": _lazy_import("sql_ddl_parser", "SQLDDLParser"),
}

_cache: dict[str, BaseParser] = {}


def get_parser(language: str) -> BaseParser | None:
    if language not in REGISTRY:
        return None
    if language not in _cache:
        try:
            _cache[language] = REGISTRY[language]()
        except ImportError:
            return None
    return _cache[language]
