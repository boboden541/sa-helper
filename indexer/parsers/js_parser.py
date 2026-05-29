"""JavaScript/TypeScript parser — extracts classes, functions, imports, calls, SQL, endpoints, services."""

from __future__ import annotations

import re
from tree_sitter import Node

import tree_sitter_javascript as tsjs
from tree_sitter import Language

from parsers.base import BaseParser
from parsers.sql_utils import looks_like_sql, is_valid_table_name, TABLE_PATTERN


class JSParser(BaseParser):
    language = Language(tsjs.language())
    extensions = [".js", ".jsx", ".ts", ".tsx"]

    def _extract_classes(self, root: Node, file_path: str, source: bytes) -> list[dict]:
        results = []
        for node in self._find_all(root, "class_declaration"):
            name_node = node.child_by_field_name("name")
            if not name_node:
                continue

            parent_class = None
            for child in node.children:
                if child.type == "class_heritage":
                    for hc in child.children:
                        if hc.type == "identifier":
                            parent_class = hc.text.decode("utf-8", errors="replace")
                            break

            results.append({
                "name": name_node.text.decode("utf-8", errors="replace"),
                "file": file_path,
                "line": node.start_point[0] + 1,
                "parent_class": parent_class,
                "interfaces": [],
            })

        for node in self._find_all(root, "class"):
            name_node = node.child_by_field_name("name")
            if name_node:
                results.append({
                    "name": name_node.text.decode("utf-8", errors="replace"),
                    "file": file_path,
                    "line": node.start_point[0] + 1,
                    "parent_class": None,
                    "interfaces": [],
                })

        return results

    def _extract_functions(self, root: Node, file_path: str, source: bytes) -> list[dict]:
        results = []
        func_types = ("function_declaration", "arrow_function", "generator_function_declaration",
                       "method_definition")

        for func_type in func_types:
            entries = self._find_all_with_parent_type(root, func_type)
            for node, class_name in entries:
                name_node = node.child_by_field_name("name")

                if func_type == "method_definition" and not name_node:
                    for child in node.children:
                        if child.type == "property_identifier":
                            name_node = child
                            break

                if not name_node:
                    continue

                params = self._extract_params(node)

                results.append({
                    "name": name_node.text.decode("utf-8", errors="replace"),
                    "file": file_path,
                    "line": node.start_point[0] + 1,
                    "parameters": params,
                    "is_method": class_name is not None,
                    "class_name": class_name,
                })
        return results

    def _extract_params(self, node: Node) -> list[str]:
        params = []
        for child in node.children:
            if child.type == "formal_parameters":
                for param in child.children:
                    if param.type == "identifier":
                        params.append(param.text.decode("utf-8", errors="replace"))
                    elif param.type == "required_parameter":
                        for pc in param.children:
                            if pc.type == "identifier":
                                params.append(pc.text.decode("utf-8", errors="replace"))
                                break
                    elif param.type == "assignment_pattern":
                        for pc in param.children:
                            if pc.type == "identifier":
                                params.append(pc.text.decode("utf-8", errors="replace"))
                                break
        return params

    def _extract_imports(self, root: Node, file_path: str, source: bytes) -> list[dict]:
        results = []
        for node in self._find_all(root, "import_statement"):
            source = None
            aliases = []

            for child in node.children:
                if child.type == "string":
                    source = child.text.decode("utf-8", errors="replace").strip("\"'")
                elif child.type == "import_clause":
                    for ic in child.children:
                        if ic.type == "identifier":
                            aliases.append(ic.text.decode("utf-8", errors="replace"))
                        elif ic.type == "named_imports":
                            for nc in ic.children:
                                if nc.type == "import_specifier":
                                    name = nc.child_by_field_name("name")
                                    alias = nc.child_by_field_name("alias")
                                    a = alias.text.decode("utf-8", errors="replace") if alias else name.text.decode("utf-8", errors="replace") if name else None
                                    if a:
                                        aliases.append(a)
                        elif ic.type == "namespace_import":
                            alias = ic.child_by_field_name("alias")
                            if alias:
                                aliases.append("* as " + alias.text.decode("utf-8", errors="replace"))

            if source:
                results.append({"source": source, "aliases": aliases, "file": file_path})

        for node in self._find_all(root, "export_statement"):
            for child in node.children:
                if child.type == "import_statement":
                    source = None
                    for sc in child.children:
                        if sc.type == "string":
                            source = sc.text.decode("utf-8", errors="replace").strip("\"'")
                    if source:
                        results.append({"source": source, "aliases": [], "file": file_path})

        return results

    def _extract_calls(self, root: Node, file_path: str, source: bytes) -> list[dict]:
        results = []
        func_types = ("function_declaration", "arrow_function", "generator_function_declaration",
                       "method_definition")

        for func_type in func_types:
            entries = self._find_all_with_parent_type(root, func_type)
            for func_node, class_name in entries:
                func_name_node = func_node.child_by_field_name("name")
                if not func_name_node:
                    if func_type == "method_definition":
                        for child in func_node.children:
                            if child.type == "property_identifier":
                                func_name_node = child
                                break
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
        elif func.type == "member_expression":
            prop = func.child_by_field_name("property")
            if prop:
                return prop.text.decode("utf-8", errors="replace")
        return None

    def _extract_tables(self, root: Node, file_path: str, source: bytes) -> list[dict]:
        """Extract SQL table names from JS/TS string literals and template literals."""
        source_str = source.decode("utf-8", errors="replace")
        results = []

        func_types = ("function_declaration", "arrow_function", "generator_function_declaration",
                       "method_definition")
        all_entries = []
        for func_type in func_types:
            all_entries.extend(self._find_all_with_parent_type(root, func_type))

        for func_node, class_name in all_entries:
            func_name_node = func_node.child_by_field_name("name")
            if not func_name_node:
                if func_node.type == "method_definition":
                    for child in func_node.children:
                        if child.type == "property_identifier":
                            func_name_node = child
                            break
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
        """Extract endpoints from Express/Koa/Fastify route definitions."""
        source_str = source.decode("utf-8", errors="replace")
        results = []
        seen = set()

        # Express: app.get('/path', ...), router.post('/path', ...)
        express_route = re.compile(
            r"""([\w.]+)\s*\.\s*(get|post|put|delete|patch|all)\s*\(\s*['"`]([^'"`]+)['"`]""",
        )

        for match in express_route.finditer(source_str):
            obj, method, route = match.group(1), match.group(2), match.group(3)
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
                    "handler_class": obj,
                    "file": file_path,
                    "line": line_no,
                    "type": "config",
                    "http_method": method.upper(),
                })

        return results

    def _extract_external_services(self, root: Node, file_path: str, source: bytes) -> list[dict]:
        """Detect external service calls: fetch(), axios, this.api.get(url), etc. with URL extraction."""
        source_str = source.decode("utf-8", errors="replace")
        results = []

        # Universal HTTP call pattern: obj.method('url')
        _HTTP_OBJECT_KEYWORDS = {"api", "http", "client", "axios", "fetch", "request", "service"}
        _HTTP_METHODS = {"get", "post", "put", "delete", "patch", "postForm", "request"}

        re_http_call = re.compile(
            r'''(\w+(?:\.\w+)*)\s*\.\s*(get|post|put|delete|patch|postForm|request)\s*(?:<[^>]*>\s*)?\(\s*['"`]([^'"`]*)['"`]'''
        )
        # fetch('url')
        re_fetch = re.compile(r'''\bfetch\s*\(\s*['"`]([^'"`]*)['"`]''')
        # new SomeClient()
        re_client = re.compile(
            r"new\s+(\w*(?:Client|Service|Api|Gateway|Provider|Adapter|Connection|Backend))\s*\(",
        )
        # Static URL prefix filter
        _URL_SKIP_PREFIXES = (
            "/static/", "/assets/", "/img/", "/css/", "/js/",
            "/favicon", "/robots.txt", "/sitemap",
        )

        def _is_api_url(url: str) -> bool:
            if not url or not url.startswith("/"):
                return False
            if len(url) < 3:
                return False
            for prefix in _URL_SKIP_PREFIXES:
                if url.startswith(prefix):
                    return False
            return True

        def _clean_url(url: str) -> str | None:
            # Strip template literal interpolation: /api/show/${id} → /api/show/
            url = re.sub(r'\$\{[^}]*\}', '', url)
            url = url.rstrip('?&#')
            if not url:
                return None
            return url

        func_types = ("function_declaration", "arrow_function", "generator_function_declaration",
                       "method_definition")
        all_entries = []
        for func_type in func_types:
            all_entries.extend(self._find_all_with_parent_type(root, func_type))

        for func_node, class_name in all_entries:
            func_name_node = func_node.child_by_field_name("name")
            if not func_name_node:
                for child in func_node.children:
                    if child.type == "property_identifier":
                        func_name_node = child
                        break
                if not func_name_node:
                    continue

            func_text = source_str[func_node.start_byte:func_node.end_byte]
            func_name = func_name_node.text.decode("utf-8", errors="replace")
            line_no = func_node.start_point[0] + 1

            # Pattern 1: this.api.get('/url'), axios.get('/url'), apiClient.post('/url')
            for match in re_http_call.finditer(func_text):
                obj_name = match.group(1)
                http_method = match.group(2)
                raw_url = match.group(3)

                # Filter: object must be HTTP-related
                obj_lower = obj_name.lower()
                is_http_obj = (
                    obj_name == "axios"
                    or any(kw in obj_lower for kw in _HTTP_OBJECT_KEYWORDS)
                    or obj_name.startswith("this.")
                )
                if not is_http_obj:
                    continue

                url = _clean_url(raw_url)

                result = {
                    "service_var": None,
                    "service_class": obj_name.split(".")[-1] if "." in obj_name else obj_name,
                    "method": http_method,
                    "function_name": func_name,
                    "file": file_path,
                    "line": line_no,
                }
                if url and _is_api_url(url):
                    result["http_url"] = url
                    result["http_method"] = http_method.upper()
                results.append(result)

            # Pattern 2: fetch('/url')
            for match in re_fetch.finditer(func_text):
                raw_url = match.group(1)
                url = _clean_url(raw_url)
                result = {
                    "service_var": None, "service_class": "fetch",
                    "method": "fetch", "function_name": func_name,
                    "file": file_path, "line": line_no,
                }
                if url and _is_api_url(url):
                    result["http_url"] = url
                    result["http_method"] = "GET"
                results.append(result)

            # Pattern 3: new SomeClient()
            for match in re_client.finditer(func_text):
                svc_class = match.group(1)
                if len(svc_class) < 3:
                    continue
                results.append({
                    "service_var": None, "service_class": svc_class,
                    "method": "__init__", "function_name": func_name,
                    "file": file_path, "line": line_no,
                })

        return results

    def _extract_framework_usage(self, root: Node, file_path: str, source: bytes) -> list[dict]:
        """Detect Express/React/Next.js patterns."""
        source_str = source.decode("utf-8", errors="replace")
        results = []

        express_pattern = re.compile(r"\bexpress\s*\(|\.Router\s*\(")
        react_pattern = re.compile(r"\b(useState|useEffect|useContext|useCallback)\s*\(")
        nextjs_pattern = re.compile(r"\b(getServerSideProps|getStaticProps|getStaticPaths)\s*\(")

        func_types = ("function_declaration", "arrow_function", "generator_function_declaration",
                       "method_definition")
        all_entries = []
        for func_type in func_types:
            all_entries.extend(self._find_all_with_parent_type(root, func_type))

        for func_node, class_name in all_entries:
            func_name_node = func_node.child_by_field_name("name")
            if not func_name_node:
                for child in func_node.children:
                    if child.type == "property_identifier":
                        func_name_node = child
                        break
                if not func_name_node:
                    continue

            func_text = source_str[func_node.start_byte:func_node.end_byte]
            func_name = func_name_node.text.decode("utf-8", errors="replace")

            for match in express_pattern.finditer(func_text):
                results.append({
                    "framework": "Express", "pattern": "router",
                    "name": "express", "type": "web_framework",
                    "function_name": func_name, "file": file_path,
                    "line": func_node.start_point[0] + 1,
                })

            for match in react_pattern.finditer(func_text):
                results.append({
                    "framework": "React", "pattern": "hook",
                    "name": match.group(1), "type": "hook",
                    "function_name": func_name, "file": file_path,
                    "line": func_node.start_point[0] + 1,
                })

            for match in nextjs_pattern.finditer(func_text):
                results.append({
                    "framework": "Next.js", "pattern": "ssr",
                    "name": match.group(1), "type": "ssr",
                    "function_name": func_name, "file": file_path,
                    "line": func_node.start_point[0] + 1,
                })

        return results
