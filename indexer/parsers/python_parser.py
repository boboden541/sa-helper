"""Python parser — extracts classes, functions, imports, calls, SQL, endpoints, services."""

from __future__ import annotations

import re
from tree_sitter import Node

import tree_sitter_python as tspython
from tree_sitter import Language

from parsers.base import BaseParser
from parsers.sql_utils import looks_like_sql, is_valid_table_name, TABLE_PATTERN


class PythonParser(BaseParser):
    language = Language(tspython.language())
    extensions = [".py"]

    def _extract_classes(self, root: Node, file_path: str, source: bytes) -> list[dict]:
        results = []
        for node in self._find_all(root, "class_definition"):
            name_node = node.child_by_field_name("name")
            if not name_node:
                continue

            parent_class = None
            arg_list = node.child_by_field_name("superclasses")
            if arg_list:
                for child in arg_list.children:
                    if child.type == "identifier":
                        parent_class = child.text.decode("utf-8", errors="replace")
                        break
                    elif child.type == "attribute":
                        parent_class = child.text.decode("utf-8", errors="replace")
                        break

            interfaces = []
            if arg_list:
                for child in arg_list.children:
                    if child.type in ("identifier", "attribute") and (
                        parent_class is None or child.text.decode("utf-8", errors="replace") != parent_class
                    ):
                        interfaces.append(child.text.decode("utf-8", errors="replace"))

            results.append({
                "name": name_node.text.decode("utf-8", errors="replace"),
                "file": file_path,
                "line": node.start_point[0] + 1,
                "parent_class": parent_class,
                "interfaces": interfaces,
            })
        return results

    def _extract_functions(self, root: Node, file_path: str, source: bytes) -> list[dict]:
        results = []
        entries = self._find_all_with_parent_type(root, "function_definition")

        for node, class_name in entries:
            name_node = node.child_by_field_name("name")
            if not name_node:
                continue

            params = node.child_by_field_name("parameters")
            param_names = []
            if params:
                for child in params.children:
                    if child.type == "identifier":
                        param_names.append(child.text.decode("utf-8", errors="replace"))
                    elif child.type == "typed_parameter":
                        ident = child.child_by_field_name("name")
                        if ident:
                            param_names.append(ident.text.decode("utf-8", errors="replace"))
                    elif child.type == "default_parameter":
                        ident = child.child_by_field_name("name")
                        if ident:
                            param_names.append(ident.text.decode("utf-8", errors="replace"))
                    elif child.type == "list_splat_pattern":
                        ident = child.child_by_field_name("name")
                        if ident:
                            param_names.append("*" + ident.text.decode("utf-8", errors="replace"))
                    elif child.type == "dictionary_splat_pattern":
                        ident = child.child_by_field_name("name")
                        if ident:
                            param_names.append("**" + ident.text.decode("utf-8", errors="replace"))

            results.append({
                "name": name_node.text.decode("utf-8", errors="replace"),
                "file": file_path,
                "line": node.start_point[0] + 1,
                "parameters": param_names,
                "is_method": class_name is not None,
                "class_name": class_name,
            })
        return results

    def _extract_imports(self, root: Node, file_path: str, source: bytes) -> list[dict]:
        results = []
        for node in self._find_all(root, "import_statement"):
            names = []
            for child in node.children:
                if child.type in ("dotted_name", "aliased_import"):
                    if child.type == "aliased_import":
                        dotted = child.child_by_field_name("name")
                        alias = child.child_by_field_name("alias")
                        name_str = dotted.text.decode("utf-8", errors="replace") if dotted else ""
                        alias_str = alias.text.decode("utf-8", errors="replace") if alias else ""
                        names.append({"source": name_str, "alias": alias_str})
                    else:
                        names.append({"source": child.text.decode("utf-8", errors="replace"), "alias": None})
            for n in names:
                results.append({"source": n["source"], "aliases": [n["alias"]] if n["alias"] else [], "file": file_path})

        for node in self._find_all(root, "import_from_statement"):
            module_name = node.child_by_field_name("module_name")
            source = module_name.text.decode("utf-8", errors="replace") if module_name else ""

            aliases = []
            for child in node.children:
                if child.type == "dotted_name" and child != module_name:
                    aliases.append(child.text.decode("utf-8", errors="replace"))
                elif child.type == "aliased_import":
                    alias = child.child_by_field_name("alias")
                    if alias:
                        aliases.append(alias.text.decode("utf-8", errors="replace"))
                elif child.type == "identifier" and child != module_name:
                    aliases.append(child.text.decode("utf-8", errors="replace"))
                elif child.type == "wildcard_import":
                    aliases.append("*")

            results.append({"source": source, "aliases": aliases, "file": file_path})
        return results

    def _extract_calls(self, root: Node, file_path: str, source: bytes) -> list[dict]:
        results = []

        func_entries = self._find_all_with_parent_type(root, "function_definition")
        for func_node, class_name in func_entries:
            func_name_node = func_node.child_by_field_name("name")
            if not func_name_node:
                continue

            call_nodes = self._find_all(func_node, "call")
            for call in call_nodes:
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
        elif func.type == "attribute":
            attr = func.child_by_field_name("attr")
            if attr:
                return attr.text.decode("utf-8", errors="replace")
        return None

    def _extract_tables(self, root: Node, file_path: str, source: bytes) -> list[dict]:
        """Extract table names from SQL string literals in Python code."""
        source_str = source.decode("utf-8", errors="replace")
        results = []

        func_entries = self._find_all_with_parent_type(root, "function_definition")
        for func_node, class_name in func_entries:
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
        """Extract endpoints from Flask/Django/FastAPI decorators."""
        source_str = source.decode("utf-8", errors="replace")
        results = []
        seen = set()

        # Flask: @app.route('/path', methods=['GET'])
        flask_route = re.compile(
            r"""@\s*[\w.]+\s*\.\s*route\s*\(\s*['"]([^'"]+)['"]\s*(?:,\s*methods\s*=\s*\[([^\]]*)\])?""",
            re.DOTALL,
        )
        # FastAPI: @router.get('/path'), @router.post('/path')
        fastapi_route = re.compile(
            r"""@\s*[\w.]+\s*\.\s*(get|post|put|delete|patch)\s*\(\s*['"]([^'"]+)['"]""",
            re.IGNORECASE,
        )
        # Django: @api_view(['GET'])
        django_view = re.compile(r"""@\s*api_view\s*\(\s*\[([^\]]*)\]""")

        func_entries = self._find_all_with_parent_type(root, "function_definition")
        for func_node, class_name in func_entries:
            name_node = func_node.child_by_field_name("name")
            if not name_node:
                continue
            func_name = name_node.text.decode("utf-8", errors="replace")

            # Check decorators (preceding comments/nodes)
            for match in flask_route.finditer(source_str[func_node.start_byte:func_node.end_byte]):
                route = match.group(1)
                methods_str = match.group(2) or "'GET'"
                http_method = re.findall(r"'(\w+)'", methods_str)
                http_method = http_method[0] if http_method else "GET"
                key = (route, func_name)
                if key not in seen:
                    seen.add(key)
                    results.append({
                        "name": route,
                        "route": route,
                        "handler_method": func_name,
                        "handler_class": class_name,
                        "file": file_path,
                        "line": func_node.start_point[0] + 1,
                        "type": "annotation",
                        "http_method": http_method.upper(),
                    })

            for match in fastapi_route.finditer(source_str[func_node.start_byte:func_node.end_byte]):
                method = match.group(1).upper()
                route = match.group(2)
                key = (route, func_name)
                if key not in seen:
                    seen.add(key)
                    results.append({
                        "name": route,
                        "route": route,
                        "handler_method": func_name,
                        "handler_class": class_name,
                        "file": file_path,
                        "line": func_node.start_point[0] + 1,
                        "type": "annotation",
                        "http_method": method,
                    })

        return results

    def _extract_external_services(self, root: Node, file_path: str, source: bytes) -> list[dict]:
        """Detect external service calls: requests.get(), httpx.Client(), etc."""
        source_str = source.decode("utf-8", errors="replace")
        results = []

        # requests.get/post/put/delete(url)
        requests_pattern = re.compile(r"requests\.(get|post|put|delete|patch|head)\s*\(")
        # httpx client
        httpx_pattern = re.compile(r"httpx\.(get|post|put|delete|patch)\s*\(")
        # aiohttp
        aiohttp_pattern = re.compile(r"aiohttp\.ClientSession\(\)")
        # grpc
        grpc_pattern = re.compile(r"grpc\.\w+\s*\(")
        # Generic client pattern
        client_pattern = re.compile(
            r"(\w*(?:Client|Service|Api|Gateway|Provider|Adapter|Connection|Backend))\s*\(\s*\)",
        )

        func_entries = self._find_all_with_parent_type(root, "function_definition")
        for func_node, class_name in func_entries:
            func_name_node = func_node.child_by_field_name("name")
            if not func_name_node:
                continue

            func_text = source_str[func_node.start_byte:func_node.end_byte]
            func_name = func_name_node.text.decode("utf-8", errors="replace")

            for match in requests_pattern.finditer(func_text):
                results.append({
                    "service_var": None, "service_class": "requests",
                    "method": match.group(1), "function_name": func_name,
                    "file": file_path, "line": func_node.start_point[0] + 1,
                })

            for match in httpx_pattern.finditer(func_text):
                results.append({
                    "service_var": None, "service_class": "httpx",
                    "method": match.group(1), "function_name": func_name,
                    "file": file_path, "line": func_node.start_point[0] + 1,
                })

            for match in aiohttp_pattern.finditer(func_text):
                results.append({
                    "service_var": None, "service_class": "aiohttp",
                    "method": "ClientSession", "function_name": func_name,
                    "file": file_path, "line": func_node.start_point[0] + 1,
                })

            for match in grpc_pattern.finditer(func_text):
                results.append({
                    "service_var": None, "service_class": "grpc",
                    "method": "dial", "function_name": func_name,
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
        """Detect Flask/Django/FastAPI patterns."""
        source_str = source.decode("utf-8", errors="replace")
        results = []

        flask_pattern = re.compile(r"\b(flask|Flask)\b")
        django_pattern = re.compile(r"\b(django|Django)\b")
        fastapi_pattern = re.compile(r"\b(FastAPI|APIRouter|Depends)\b")
        sqlalchemy_pattern = re.compile(r"\b(Session|sessionmaker|create_engine|Column|relationship)\b")

        func_entries = self._find_all_with_parent_type(root, "function_definition")
        for func_node, class_name in func_entries:
            func_name_node = func_node.child_by_field_name("name")
            if not func_name_node:
                continue

            func_text = source_str[func_node.start_byte:func_node.end_byte]
            func_name = func_name_node.text.decode("utf-8", errors="replace")

            if flask_pattern.search(func_text):
                results.append({
                    "framework": "Flask", "pattern": "import",
                    "name": "flask", "type": "web_framework",
                    "function_name": func_name, "file": file_path,
                    "line": func_node.start_point[0] + 1,
                })

            if fastapi_pattern.search(func_text):
                results.append({
                    "framework": "FastAPI", "pattern": "import",
                    "name": "fastapi", "type": "web_framework",
                    "function_name": func_name, "file": file_path,
                    "line": func_node.start_point[0] + 1,
                })

            if sqlalchemy_pattern.search(func_text):
                results.append({
                    "framework": "SQLAlchemy", "pattern": "orm",
                    "name": "sqlalchemy", "type": "database",
                    "function_name": func_name, "file": file_path,
                    "line": func_node.start_point[0] + 1,
                })

        return results
