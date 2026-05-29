"""Java parser — extracts classes, methods, imports, calls, SQL, endpoints, services."""

from __future__ import annotations

import re
from tree_sitter import Node

import tree_sitter_java as tsjava
from tree_sitter import Language

from parsers.base import BaseParser
from parsers.sql_utils import looks_like_sql, is_valid_table_name, TABLE_PATTERN


class JavaParser(BaseParser):
    language = Language(tsjava.language())
    extensions = [".java"]

    def _extract_classes(self, root: Node, file_path: str, source: bytes) -> list[dict]:
        results = []
        for node in self._find_all(root, "class_declaration"):
            name_node = node.child_by_field_name("name")
            if not name_node:
                continue

            parent_class = None
            for child in node.children:
                if child.type == "superclass":
                    for t in child.children:
                        if t.type == "type_identifier":
                            parent_class = t.text.decode("utf-8", errors="replace")
                            break

            interfaces = []
            for child in node.children:
                if child.type == "super_interfaces":
                    for t in child.children:
                        if t.type == "type_list":
                            for tc in t.children:
                                if tc.type == "type_identifier":
                                    interfaces.append(tc.text.decode("utf-8", errors="replace"))

            results.append({
                "name": name_node.text.decode("utf-8", errors="replace"),
                "file": file_path,
                "line": node.start_point[0] + 1,
                "parent_class": parent_class,
                "interfaces": interfaces,
            })

        for node in self._find_all(root, "interface_declaration"):
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
        entries = self._find_all_with_parent_type(root, "method_declaration")

        for node, class_name in entries:
            name_node = node.child_by_field_name("name")
            if not name_node:
                continue

            params = []
            for child in node.children:
                if child.type == "formal_parameters":
                    for param in child.children:
                        if param.type == "formal_parameter":
                            p_name = param.child_by_field_name("name")
                            if p_name:
                                params.append(p_name.text.decode("utf-8", errors="replace"))

            results.append({
                "name": name_node.text.decode("utf-8", errors="replace"),
                "file": file_path,
                "line": node.start_point[0] + 1,
                "parameters": params,
                "is_method": True,
                "class_name": class_name,
            })

        for node in self._find_all(root, "constructor_declaration"):
            name_node = node.child_by_field_name("name")
            if not name_node:
                continue
            class_name_node = node.child_by_field_name("type")
            class_name = class_name_node.text.decode("utf-8", errors="replace") if class_name_node else None

            params = []
            for child in node.children:
                if child.type == "formal_parameters":
                    for param in child.children:
                        if param.type == "formal_parameter":
                            p_name = param.child_by_field_name("name")
                            if p_name:
                                params.append(p_name.text.decode("utf-8", errors="replace"))

            results.append({
                "name": name_node.text.decode("utf-8", errors="replace"),
                "file": file_path,
                "line": node.start_point[0] + 1,
                "parameters": params,
                "is_method": True,
                "class_name": class_name,
            })

        return results

    def _extract_imports(self, root: Node, file_path: str, source: bytes) -> list[dict]:
        results = []
        for node in self._find_all(root, "import_declaration"):
            source = None
            aliases = []
            is_wildcard = False

            for child in node.children:
                if child.type == "scoped_identifier":
                    source = child.text.decode("utf-8", errors="replace")
                elif child.type == "asterisk":
                    is_wildcard = True
                elif child.type == "identifier":
                    if source:
                        aliases.append(child.text.decode("utf-8", errors="replace"))

            if source:
                if is_wildcard:
                    source += ".*"
                results.append({"source": source, "aliases": aliases, "file": file_path})

        return results

    def _extract_calls(self, root: Node, file_path: str, source: bytes) -> list[dict]:
        results = []
        func_entries = self._find_all_with_parent_type(root, "method_declaration")

        for func_node, class_name in func_entries:
            func_name_node = func_node.child_by_field_name("name")
            if not func_name_node:
                continue

            for call in self._find_all(func_node, "method_invocation"):
                name = call.child_by_field_name("name")
                if name:
                    results.append({
                        "caller_name": func_name_node.text.decode("utf-8", errors="replace"),
                        "caller_file": file_path,
                        "caller_line": func_node.start_point[0] + 1,
                        "callee_name": name.text.decode("utf-8", errors="replace"),
                    })
        return results

    def _extract_tables(self, root: Node, file_path: str, source: bytes) -> list[dict]:
        """Extract SQL table names from Java string literals."""
        source_str = source.decode("utf-8", errors="replace")
        results = []

        func_entries = self._find_all_with_parent_type(root, "method_declaration")
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

        # JPA @Table(name = "users") annotations
        table_ann = re.compile(r'@Table\s*\(\s*(?:name\s*=\s*)?["\'](\w+)["\']', re.IGNORECASE)
        for node in self._find_all(root, "class_declaration"):
            name_node = node.child_by_field_name("name")
            if not name_node:
                continue
            cls_text = source_str[node.start_byte:node.end_byte]
            for match in table_ann.finditer(cls_text):
                table_name = match.group(1)
                if is_valid_table_name(table_name):
                    results.append({
                        "name": table_name,
                        "source_file": file_path,
                        "source_line": node.start_point[0] + 1,
                        "function_name": name_node.text.decode("utf-8", errors="replace"),
                        "file": file_path,
                        "type": "table",
                    })

        return results

    def _extract_endpoints(self, root: Node, file_path: str, source: bytes) -> list[dict]:
        """Extract endpoints from Spring @RequestMapping/@GetMapping/etc."""
        source_str = source.decode("utf-8", errors="replace")
        results = []
        seen = set()

        # @RequestMapping("/path"), @GetMapping("/path"), @PostMapping("/path"), etc.
        mapping_re = re.compile(
            r'@(?:Request|Get|Post|Put|Delete|Patch)Mapping\s*\(\s*(?:value\s*=\s*|path\s*=\s*)?["\']([^"\']+)["\']',
        )
        method_map = {
            "GET": "GetMapping", "POST": "PostMapping", "PUT": "PutMapping",
            "DELETE": "DeleteMapping", "PATCH": "PatchMapping",
        }

        func_entries = self._find_all_with_parent_type(root, "method_declaration")
        for func_node, class_name in func_entries:
            name_node = func_node.child_by_field_name("name")
            if not name_node:
                continue
            func_name = name_node.text.decode("utf-8", errors="replace")

            # Scan annotations on method — they appear as siblings before the method
            start = source_str[:func_node.start_byte].rstrip()
            # Look for annotations in the 500 chars before the method
            prefix = source_str[max(0, func_node.start_byte - 500):func_node.start_byte]

            for match in mapping_re.finditer(prefix):
                route = match.group(1)
                ann_text = match.group(0)
                http_method = "ANY"
                for m, ann_name in method_map.items():
                    if ann_name in ann_text:
                        http_method = m
                        break
                if "RequestMapping" in ann_text:
                    http_method = "ANY"
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
                        "http_method": http_method,
                    })

        return results

    def _extract_external_services(self, root: Node, file_path: str, source: bytes) -> list[dict]:
        """Detect external service calls: RestTemplate, WebClient, HttpClient."""
        source_str = source.decode("utf-8", errors="replace")
        results = []

        rest_template = re.compile(r'\bRestTemplate\b')
        web_client = re.compile(r'\bWebClient\b')
        http_client = re.compile(r'\bHttpClient\b')
        client_pattern = re.compile(
            r'new\s+(\w*(?:Client|Service|Api|Gateway|Provider|Adapter|Connection|Backend))\s*\(',
        )

        func_entries = self._find_all_with_parent_type(root, "method_declaration")
        for func_node, class_name in func_entries:
            func_name_node = func_node.child_by_field_name("name")
            if not func_name_node:
                continue

            func_text = source_str[func_node.start_byte:func_node.end_byte]
            func_name = func_name_node.text.decode("utf-8", errors="replace")

            if rest_template.search(func_text):
                results.append({
                    "service_var": None, "service_class": "RestTemplate",
                    "method": "__init__", "function_name": func_name,
                    "file": file_path, "line": func_node.start_point[0] + 1,
                })

            if web_client.search(func_text):
                results.append({
                    "service_var": None, "service_class": "WebClient",
                    "method": "__init__", "function_name": func_name,
                    "file": file_path, "line": func_node.start_point[0] + 1,
                })

            if http_client.search(func_text):
                results.append({
                    "service_var": None, "service_class": "HttpClient",
                    "method": "__init__", "function_name": func_name,
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
        """Detect Spring/JPA/Lombok patterns."""
        source_str = source.decode("utf-8", errors="replace")
        results = []

        spring_pattern = re.compile(r'@(?:Autowired|Service|Repository|Component|Controller|RestController|Configuration)')
        jpa_pattern = re.compile(r'@(?:Entity|Column|Table|Query|Id|ManyToOne|OneToMany|ManyToMany|OneToOne)')
        lombok_pattern = re.compile(r'@(?:Data|Builder|Getter|Setter|AllArgsConstructor|NoArgsConstructor|Slf4j)')

        func_entries = self._find_all_with_parent_type(root, "method_declaration")
        for func_node, class_name in func_entries:
            func_name_node = func_node.child_by_field_name("name")
            if not func_name_node:
                continue

            func_text = source_str[func_node.start_byte:func_node.end_byte]
            func_name = func_name_node.text.decode("utf-8", errors="replace")

            for match in spring_pattern.finditer(func_text):
                ann = match.group(0)[1:]  # strip @
                results.append({
                    "framework": "Spring", "pattern": "annotation",
                    "name": ann, "type": "web_framework",
                    "function_name": func_name, "file": file_path,
                    "line": func_node.start_point[0] + 1,
                })

            for match in jpa_pattern.finditer(func_text):
                ann = match.group(0)[1:]
                results.append({
                    "framework": "JPA", "pattern": "annotation",
                    "name": ann, "type": "database",
                    "function_name": func_name, "file": file_path,
                    "line": func_node.start_point[0] + 1,
                })

            for match in lombok_pattern.finditer(func_text):
                ann = match.group(0)[1:]
                results.append({
                    "framework": "Lombok", "pattern": "annotation",
                    "name": ann, "type": "utility",
                    "function_name": func_name, "file": file_path,
                    "line": func_node.start_point[0] + 1,
                })

        return results
