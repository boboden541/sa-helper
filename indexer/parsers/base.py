"""Base parser with shared tree-sitter logic for all languages."""

from __future__ import annotations

from abc import ABC, abstractmethod
from tree_sitter import Language, Parser, Node


class BaseParser(ABC):
    language: Language
    extensions: list[str]

    def __init__(self):
        self._parser = Parser(self.language)

    def parse(self, source_code: bytes, file_path: str) -> dict:
        tree = self._parser.parse(source_code)
        root = tree.root_node
        return {
            "classes": self._extract_classes(root, file_path, source_code),
            "functions": self._extract_functions(root, file_path, source_code),
            "imports": self._extract_imports(root, file_path, source_code),
            "calls": self._extract_calls(root, file_path, source_code),
            "tables": self._extract_tables(root, file_path, source_code),
            "endpoints": self._extract_endpoints(root, file_path, source_code),
            "external_services": self._extract_external_services(root, file_path, source_code),
            "framework_usage": self._extract_framework_usage(root, file_path, source_code),
            "config_entries": [],
            "scheduled_tasks": [],
        }

    @abstractmethod
    def _extract_classes(self, root: Node, file_path: str, source: bytes) -> list[dict]:
        ...

    @abstractmethod
    def _extract_functions(self, root: Node, file_path: str, source: bytes) -> list[dict]:
        ...

    @abstractmethod
    def _extract_imports(self, root: Node, file_path: str, source: bytes) -> list[dict]:
        ...

    @abstractmethod
    def _extract_calls(self, root: Node, file_path: str, source: bytes) -> list[dict]:
        ...

    def _extract_tables(self, root: Node, file_path: str, source: bytes) -> list[dict]:
        """Default: extract table names from SQL-like string literals."""
        return []

    def _extract_endpoints(self, root: Node, file_path: str, source: bytes) -> list[dict]:
        return []

    def _extract_external_services(self, root: Node, file_path: str, source: bytes) -> list[dict]:
        return []

    def _extract_framework_usage(self, root: Node, file_path: str, source: bytes) -> list[dict]:
        return []

    @staticmethod
    def _node_text(node: Node, source: bytes) -> str:
        return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")

    def _find_all(self, node: Node, type_name: str) -> list[Node]:
        results = []
        if node.type == type_name:
            results.append(node)
        for child in node.children:
            results.extend(self._find_all(child, type_name))
        return results

    def _find_all_with_parent_type(self, root: Node, target_type: str) -> list[tuple[Node, str]]:
        """Find all nodes of target_type and track the nearest enclosing class name."""
        results = []

        def walk(node: Node, parent_name: str | None = None):
            current_parent = parent_name

            if node.type in ("class_definition", "class_declaration", "class",
                             "interface_declaration", "struct_declaration",
                             "trait_declaration"):
                name_node = node.child_by_field_name("name")
                if name_node:
                    current_parent = name_node.text.decode("utf-8", errors="replace")

            if node.type == target_type:
                results.append((node, current_parent))

            for child in node.children:
                walk(child, current_parent)

        walk(root)
        return results
