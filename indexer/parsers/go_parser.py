"""Go parser — extracts structs, functions, imports, calls, SQL, endpoints, services."""

from __future__ import annotations

import re
from tree_sitter import Node

import tree_sitter_go as tsgo
from tree_sitter import Language

from parsers.base import BaseParser
from parsers.sql_utils import looks_like_sql, is_valid_table_name, TABLE_PATTERN


class GoParser(BaseParser):
    language = Language(tsgo.language())
    extensions = [".go"]

    def _extract_classes(self, root: Node, file_path: str, source: bytes) -> list[dict]:
        results = []

        for node in self._find_all(root, "type_declaration"):
            for child in node.children:
                if child.type == "type_spec":
                    name_node = child.child_by_field_name("name")
                    type_node = child.child_by_field_name("type")
                    if not name_node:
                        continue

                    type_name = type_node.type if type_node else ""

                    interfaces = []
                    if type_node and type_node.type == "interface_type":
                        for mc in type_node.children:
                            if mc.type == "method_spec":
                                mn = mc.child_by_field_name("name")
                                if mn:
                                    interfaces.append(mn.text.decode("utf-8", errors="replace"))

                    results.append({
                        "name": name_node.text.decode("utf-8", errors="replace"),
                        "file": file_path,
                        "line": node.start_point[0] + 1,
                        "parent_class": None,
                        "interfaces": interfaces,
                    })

        return results

    def _extract_functions(self, root: Node, file_path: str, source: bytes) -> list[dict]:
        results = []

        for node in self._find_all(root, "function_declaration"):
            name_node = node.child_by_field_name("name")
            if not name_node:
                continue

            params = self._extract_params(node)
            receiver_name = None

            results.append({
                "name": name_node.text.decode("utf-8", errors="replace"),
                "file": file_path,
                "line": node.start_point[0] + 1,
                "parameters": params,
                "is_method": False,
                "class_name": None,
            })

        for node in self._find_all(root, "method_declaration"):
            name_node = node.child_by_field_name("name")
            if not name_node:
                continue

            receiver = node.child_by_field_name("receiver")
            class_name = None
            if receiver:
                for rc in receiver.children:
                    if rc.type == "parameter_list":
                        for rpc in rc.children:
                            if rpc.type == "parameter_declaration":
                                t = rpc.child_by_field_name("type")
                                if t:
                                    class_name = t.text.decode("utf-8", errors="replace").strip("*")
                                    break

            params = self._extract_params(node)

            results.append({
                "name": name_node.text.decode("utf-8", errors="replace"),
                "file": file_path,
                "line": node.start_point[0] + 1,
                "parameters": params,
                "is_method": True,
                "class_name": class_name,
            })

        return results

    def _extract_params(self, node: Node) -> list[str]:
        params = []
        for child in node.children:
            if child.type == "parameter_list":
                for param in child.children:
                    if param.type == "parameter_declaration":
                        name = param.child_by_field_name("name")
                        if name:
                            params.append(name.text.decode("utf-8", errors="replace"))
                    elif param.type == "variadic_parameter_declaration":
                        name = param.child_by_field_name("name")
                        if name:
                            params.append("..." + name.text.decode("utf-8", errors="replace"))
        return params

    def _extract_imports(self, root: Node, file_path: str, source: bytes) -> list[dict]:
        results = []

        for node in self._find_all(root, "import_declaration"):
            for child in node.children:
                if child.type == "import_spec":
                    path_node = child.child_by_field_name("path")
                    alias_node = child.child_by_field_name("name")
                    if path_node:
                        source = path_node.text.decode("utf-8", errors="replace").strip("\"")
                        alias = alias_node.text.decode("utf-8", errors="replace") if alias_node else None
                        results.append({
                            "source": source,
                            "aliases": [alias] if alias and alias != "_" else [],
                            "file": file_path,
                        })
                elif child.type == "import_spec_list":
                    for spec in child.children:
                        if spec.type == "import_spec":
                            path_node = spec.child_by_field_name("path")
                            alias_node = spec.child_by_field_name("name")
                            if path_node:
                                source = path_node.text.decode("utf-8", errors="replace").strip("\"")
                                alias = alias_node.text.decode("utf-8", errors="replace") if alias_node else None
                                results.append({
                                    "source": source,
                                    "aliases": [alias] if alias and alias != "_" else [],
                                    "file": file_path,
                                })

        return results

    def _extract_calls(self, root: Node, file_path: str, source: bytes) -> list[dict]:
        results = []
        all_funcs = list(self._find_all_with_parent_type(root, "function_declaration"))
        all_funcs.extend(self._find_all_with_parent_type(root, "method_declaration"))

        for func_node, _ in all_funcs:
            func_name_node = func_node.child_by_field_name("name")
            if not func_name_node:
                continue

            for call in self._find_all(func_node, "call_expression"):
                callee_name = self._get_call_name(call)
                if callee_name:
                    results.append({
                        "caller_name": func_name_node.text.decode("utf-8", errors="replace"),
                        "caller_file": file_path,
                        "caller_line": func_node.start_point[0] + 1,
                        "callee_name": callee_name,
                    })
        return results

    def _get_call_name(self, call_node: Node) -> str | None:
        func = call_node.child_by_field_name("function")
        if not func:
            return None

        if func.type == "identifier":
            return func.text.decode("utf-8", errors="replace")
        elif func.type == "selector_expression":
            field = func.child_by_field_name("field")
            if field:
                return field.text.decode("utf-8", errors="replace")
        return None

    def _extract_tables(self, root: Node, file_path: str, source: bytes) -> list[dict]:
        """Extract SQL table names from Go string literals."""
        source_str = source.decode("utf-8", errors="replace")
        results = []

        all_funcs = list(self._find_all_with_parent_type(root, "function_declaration"))
        all_funcs.extend(self._find_all_with_parent_type(root, "method_declaration"))

        for func_node, class_name in all_funcs:
            func_name_node = func_node.child_by_field_name("name")
            if not func_name_node:
                continue

            func_text = source_str[func_node.start_byte:func_node.end_byte]
            if not looks_like_sql(func_text):
                continue

            func_name = func_name_node.text.decode("utf-8", errors="replace")
            for match in TABLE_PATTERN.finditer(func_text):
                table_name = match.group(1) or match.group(2)
                if not table_name or not is_valid_table_name(table_name):
                    continue
                results.append({
                    "name": table_name,
                    "source_file": file_path,
                    "source_line": func_node.start_point[0] + 1,
                    "function_name": func_name,
                    "file": file_path,
                    "type": "table",
                })

        return results

    def _extract_endpoints(self, root: Node, file_path: str, source: bytes) -> list[dict]:
        """Extract endpoints from net/http, Gin, Echo route definitions."""
        source_str = source.decode("utf-8", errors="replace")
        results = []
        seen = set()

        # net/http: http.HandleFunc("/path", handler)
        http_handle = re.compile(
            r'(?:http\.(?:HandleFunc|Handle))\s*\(\s*["`]([^"`]+)["`]',
        )
        # Gin: r.GET("/path", ...), router.POST("/path", ...)
        gin_route = re.compile(
            r'[\w.]+\s*\.\s*(GET|POST|PUT|DELETE|PATCH)\s*\(\s*["`]([^"`]+)["`]',
        )
        # Echo: e.GET("/path", ...)
        echo_route = re.compile(
            r'[\w.]+\s*\.\s*(GET|POST|PUT|DELETE|PATCH)\s*\(\s*["`]([^"`]+)["`]',
        )

        for match in http_handle.finditer(source_str):
            route = match.group(1)
            if not route.startswith("/"):
                continue
            key = (route, "ANY")
            if key not in seen:
                seen.add(key)
                line_no = source_str[:match.start()].count("\n") + 1
                results.append({
                    "name": route,
                    "route": route,
                    "handler_method": None,
                    "handler_class": None,
                    "file": file_path,
                    "line": line_no,
                    "type": "config",
                    "http_method": "ANY",
                })

        for match in gin_route.finditer(source_str):
            method, route = match.group(1), match.group(2)
            if not route.startswith("/"):
                continue
            key = (route, method)
            if key not in seen:
                seen.add(key)
                line_no = source_str[:match.start()].count("\n") + 1
                results.append({
                    "name": route,
                    "route": route,
                    "handler_method": None,
                    "handler_class": None,
                    "file": file_path,
                    "line": line_no,
                    "type": "config",
                    "http_method": method,
                })

        return results

    def _extract_external_services(self, root: Node, file_path: str, source: bytes) -> list[dict]:
        """Detect external service calls: http.Client{}, grpc.Dial(), redis."""
        source_str = source.decode("utf-8", errors="replace")
        results = []

        http_client = re.compile(r'http\.Client\s*\{')
        grpc_pattern = re.compile(r'grpc\.\w+\s*\(')
        redis_pattern = re.compile(r'''redis\.NewClient\s*\(''')
        client_pattern = re.compile(
            r'(\w*(?:Client|Service|Api|Gateway|Provider|Adapter|Connection|Backend))\s*\{',
        )

        all_funcs = list(self._find_all_with_parent_type(root, "function_declaration"))
        all_funcs.extend(self._find_all_with_parent_type(root, "method_declaration"))

        for func_node, class_name in all_funcs:
            func_name_node = func_node.child_by_field_name("name")
            if not func_name_node:
                continue

            func_text = source_str[func_node.start_byte:func_node.end_byte]
            func_name = func_name_node.text.decode("utf-8", errors="replace")

            if http_client.search(func_text):
                results.append({
                    "service_var": None, "service_class": "http.Client",
                    "method": "__init__", "function_name": func_name,
                    "file": file_path, "line": func_node.start_point[0] + 1,
                })

            for match in grpc_pattern.finditer(func_text):
                results.append({
                    "service_var": None, "service_class": "grpc",
                    "method": "dial", "function_name": func_name,
                    "file": file_path, "line": func_node.start_point[0] + 1,
                })

            if redis_pattern.search(func_text):
                results.append({
                    "service_var": None, "service_class": "redis",
                    "method": "NewClient", "function_name": func_name,
                    "file": file_path, "line": func_node.start_point[0] + 1,
                })

            for match in client_pattern.finditer(func_text):
                svc_class = match.group(1)
                if len(svc_class) < 3:
                    continue
                results.append({
                    "service_var": None, "service_class": svc_class,
                    "method": "__init__", "function_name": func_name,
                    "file": file_path, "line": func_node.start_point[0] + 1,
                })

        return results

    def _extract_framework_usage(self, root: Node, file_path: str, source: bytes) -> list[dict]:
        """Detect Gin, Echo, GORM patterns."""
        source_str = source.decode("utf-8", errors="replace")
        results = []

        gin_pattern = re.compile(r'\bgin\.(Default|New|H)\b')
        echo_pattern = re.compile(r'\becho\.New\s*\(\s*\)')
        gorm_pattern = re.compile(r'\bgorm\.(Open|Model|DB)\b')

        all_funcs = list(self._find_all_with_parent_type(root, "function_declaration"))
        all_funcs.extend(self._find_all_with_parent_type(root, "method_declaration"))

        for func_node, class_name in all_funcs:
            func_name_node = func_node.child_by_field_name("name")
            if not func_name_node:
                continue

            func_text = source_str[func_node.start_byte:func_node.end_byte]
            func_name = func_name_node.text.decode("utf-8", errors="replace")

            for match in gin_pattern.finditer(func_text):
                results.append({
                    "framework": "Gin", "pattern": "router",
                    "name": "gin", "type": "web_framework",
                    "function_name": func_name, "file": file_path,
                    "line": func_node.start_point[0] + 1,
                })

            if echo_pattern.search(func_text):
                results.append({
                    "framework": "Echo", "pattern": "router",
                    "name": "echo", "type": "web_framework",
                    "function_name": func_name, "file": file_path,
                    "line": func_node.start_point[0] + 1,
                })

            for match in gorm_pattern.finditer(func_text):
                results.append({
                    "framework": "GORM", "pattern": "orm",
                    "name": "gorm", "type": "database",
                    "function_name": func_name, "file": file_path,
                    "line": func_node.start_point[0] + 1,
                })

        return results
