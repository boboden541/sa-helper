"""PHP parser — extracts classes, functions, use statements, method calls, SQL, Yii patterns."""

from __future__ import annotations

import re
from tree_sitter import Node

import tree_sitter_php as tsphp
from tree_sitter import Language

from parsers.base import BaseParser
from parsers.config_parser import _classify_entry
from parsers.sql_utils import (
    SQL_KEYWORDS, SQL_FALSE_POSITIVES, TABLE_PATTERN,
    looks_like_sql, is_valid_table_name, clean_concat,
)


_PHP_FALSE_POSITIVES = {
    "function", "this", "self", "parent", "class", "new", "return",
    "echo", "print", "isset", "unset", "empty", "list", "array",
    "include", "require", "include_once", "require_once",
    "preg_match", "preg_match_all", "preg_replace",
    "curl_exec", "shell_exec", "exec", "system", "passthru",
    "call_user_func", "call_user_func_array",
    "mysqli_query", "mysql_query", "pg_query",
    "forward_static_call", "forward_static_call_array",
    "method_exists", "is_callable",
}


def _is_valid_sp_name(name: str) -> bool:
    """Filter out SQL keywords and PHP false positives from SP name matches."""
    if len(name) <= 2:
        return False
    upper = name.upper()
    if upper in SQL_KEYWORDS or upper in SQL_FALSE_POSITIVES:
        return False
    if name in _PHP_FALSE_POSITIVES or name.lower() in _PHP_FALSE_POSITIVES:
        return False
    # CamelCase without underscore = likely a PHP class, not a SP
    if re.match(r'^[A-Z][a-zA-Z]+$', name) and '_' not in name:
        return False
    # All lowercase single word = likely a PHP function
    if name.islower() and '_' not in name:
        return False
    return True


def _get_php_language():
    """tree-sitter-php exposes language differently depending on version."""
    if hasattr(tsphp, "language_php"):
        return Language(tsphp.language_php())
    if hasattr(tsphp, "language"):
        return Language(tsphp.language())
    try:
        from tree_sitter_php import language as _lang_func
        return Language(_lang_func())
    except (ImportError, TypeError):
        pass
    raise ImportError(
        "Cannot load PHP language from tree_sitter_php. "
        "Try: pip install --upgrade tree-sitter-php"
    )


class PHPParser(BaseParser):
    language = _get_php_language()
    extensions = [".php"]

    def _get_all_function_entries(self, root: Node) -> list[tuple[Node, str | None]]:
        """Get both standalone functions and class methods with parent class names."""
        entries = self._find_all_with_parent_type(root, "function_definition")
        entries += self._find_all_with_parent_type(root, "method_declaration")
        return entries

    def _extract_classes(self, root: Node, file_path: str, source: bytes) -> list[dict]:
        results = []
        for node in self._find_all(root, "class_declaration"):
            name_node = node.child_by_field_name("name")
            if not name_node:
                continue

            parent_class = None
            for child in node.children:
                if child.type == "base_clause":
                    for bc_child in child.children:
                        if bc_child.type in ("name", "namespace_name", "qualified_name"):
                            parent_class = bc_child.text.decode("utf-8", errors="replace").strip("\\")
                            break
                    if not parent_class:
                        name = child.child_by_field_name("name")
                        if name:
                            parent_class = name.text.decode("utf-8", errors="replace").strip("\\")
                    break

            interfaces = []
            for child in node.children:
                if child.type == "class_interface_clause":
                    for iface_child in child.children:
                        if iface_child.type in ("name", "namespace_name", "qualified_name"):
                            interfaces.append(iface_child.text.decode("utf-8", errors="replace").strip("\\"))
                    break

            results.append({
                "name": name_node.text.decode("utf-8", errors="replace"),
                "file": file_path,
                "line": node.start_point[0] + 1,
                "parent_class": parent_class,
                "interfaces": interfaces,
            })

        for node in self._find_all(root, "trait_declaration"):
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
        entries = self._get_all_function_entries(root)

        for node, class_name in entries:
            name_node = node.child_by_field_name("name")
            if not name_node:
                continue

            func_name = name_node.text.decode("utf-8", errors="replace")
            params = []
            for child in node.children:
                if child.type == "formal_parameters":
                    for param in child.children:
                        if param.type == "simple_parameter":
                            var = param.child_by_field_name("name")
                            if var:
                                params.append(var.text.decode("utf-8", errors="replace").lstrip("$"))

            is_action = func_name.startswith("action")

            results.append({
                "name": func_name,
                "file": file_path,
                "line": node.start_point[0] + 1,
                "parameters": params,
                "is_method": class_name is not None,
                "class_name": class_name,
                "is_entry_point": is_action,
            })
        return results

    def _extract_imports(self, root: Node, file_path: str, source: bytes) -> list[dict]:
        results = []
        for node in self._find_all(root, "namespace_use_declaration"):
            ns_prefix = None

            for child in node.children:
                if child.type in ("namespace_name", "namespace_name_as_prefix"):
                    ns_prefix = child.text.decode("utf-8", errors="replace").strip("\\")
                elif child.type == "namespace_use_group":
                    for group_child in child.children:
                        if group_child.type in ("namespace_use_group_clause", "namespace_use_clause"):
                            result = self._parse_use_clause(group_child, ns_prefix, file_path)
                            if result:
                                results.append(result)
                elif child.type in ("namespace_use_clause", "namespace_use_group_clause"):
                    result = self._parse_use_clause(child, ns_prefix, file_path)
                    if result:
                        results.append(result)

        return results

    def _parse_use_clause(self, clause: Node, prefix: str | None, file_path: str) -> dict | None:
        # Try both field name variants (version-dependent)
        ns_node = clause.child_by_field_name("name") or clause.child_by_field_name("namespace")
        alias_node = clause.child_by_field_name("alias")

        # Fallback: look at children for namespace-like nodes
        if not ns_node:
            for sub in clause.children:
                if sub.type in ("qualified_name", "namespace_name", "name"):
                    ns_node = sub
                    break

        if not ns_node:
            return None

        full_source = ns_node.text.decode("utf-8", errors="replace").strip("\\")
        if prefix and not full_source.startswith(prefix):
            full_source = prefix + "\\" + full_source

        alias = alias_node.text.decode("utf-8", errors="replace") if alias_node else None

        return {
            "source": full_source,
            "aliases": [alias] if alias else [],
            "file": file_path,
        }

    def _extract_calls(self, root: Node, file_path: str, source: bytes) -> list[dict]:
        results = []
        func_entries = self._get_all_function_entries(root)

        for func_node, class_name in func_entries:
            func_name_node = func_node.child_by_field_name("name")
            if not func_name_node:
                continue

            func_name = func_name_node.text.decode("utf-8", errors="replace")

            # Function calls: func_name()
            for call in self._find_all(func_node, "function_call_expression"):
                callee_name = self._get_call_name(call)
                if callee_name and not callee_name.startswith("__"):
                    results.append({
                        "caller_name": func_name,
                        "caller_file": file_path,
                        "caller_line": func_node.start_point[0] + 1,
                        "callee_name": callee_name,
                    })

            # Method calls: $obj->method()
            for call in self._find_all(func_node, "member_call_expression"):
                name = call.child_by_field_name("name")
                if name:
                    callee = name.text.decode("utf-8", errors="replace")
                    if callee.startswith("__"):
                        continue

                    # Detect $this->method() self-calls for precise resolution
                    obj = call.child_by_field_name("object")
                    obj_text = obj.text.decode("utf-8", errors="replace") if obj else ""
                    callee_file = file_path if obj_text == "$this" else None

                    results.append({
                        "caller_name": func_name,
                        "caller_file": file_path,
                        "caller_line": func_node.start_point[0] + 1,
                        "callee_name": callee,
                        "callee_file": callee_file,
                    })

            # Static calls: ClassName::method()
            for call in self._find_all(func_node, "scoped_call_expression"):
                name = call.child_by_field_name("name")
                if name:
                    callee = name.text.decode("utf-8", errors="replace")
                    if not callee.startswith("__"):
                        results.append({
                            "caller_name": func_name,
                            "caller_file": file_path,
                            "caller_line": func_node.start_point[0] + 1,
                            "callee_name": callee,
                        })

        return results

    def _get_call_name(self, call_node: Node) -> str | None:
        for child in call_node.children:
            if child.type == "name":
                return child.text.decode("utf-8", errors="replace")
            elif child.type in ("member_access", "member_access_expression"):
                name = child.child_by_field_name("name")
                if name:
                    return name.text.decode("utf-8", errors="replace")
        return None

    def _extract_tables(self, root: Node, file_path: str, source: bytes) -> list[dict]:
        """Extract SQL table names and stored procedures from PHP code."""
        source_str = source.decode("utf-8", errors="replace")

        # EXEC with optional schema (defaults to dbo)
        sp_pattern = re.compile(r"EXEC(?:UTE)?\s+(?:(\w+)\.)?(\w+)", re.IGNORECASE)
        # CALL with optional schema
        call_pattern = re.compile(r"CALL\s+(?:(\w+)\.)?(\w+)", re.IGNORECASE)
        # CActiveRecord patterns: ClassName::model()->...
        ar_pattern = re.compile(r'(\w+)::model\(\)', re.IGNORECASE)
        # tableName() return value
        tablename_pattern = re.compile(
            r"function\s+tableName\s*\(.*?\)\s*\{[^}]*return\s+['\"]([^'\"]+)['\"]",
            re.IGNORECASE | re.DOTALL,
        )

        results = []
        func_entries = self._get_all_function_entries(root)

        for func_node, class_name in func_entries:
            func_name_node = func_node.child_by_field_name("name")
            if not func_name_node:
                continue

            func_text = clean_concat(source_str[func_node.start_byte:func_node.end_byte])
            func_name = func_name_node.text.decode("utf-8", errors="replace")

            if not looks_like_sql(func_text):
                continue

            # SQL tables
            for match in TABLE_PATTERN.finditer(func_text):
                table_name = match.group(1) or match.group(2)
                if not table_name:
                    continue
                if not is_valid_table_name(table_name):
                    continue

                results.append({
                    "name": table_name,
                    "schema": None,
                    "source_file": file_path,
                    "source_line": func_node.start_point[0] + 1,
                    "function_name": func_name,
                    "file": file_path,
                    "type": "table",
                })

            # Stored procedures: EXECUTE [schema.]name
            for match in sp_pattern.finditer(func_text):
                schema = match.group(1) or None
                sp_name = match.group(2)
                if not _is_valid_sp_name(sp_name):
                    continue
                results.append({
                    "name": sp_name,
                    "schema": schema,
                    "source_file": file_path,
                    "source_line": func_node.start_point[0] + 1,
                    "function_name": func_name,
                    "file": file_path,
                    "type": "stored_procedure",
                })

            # CALL pattern: CALL [schema.]name
            for match in call_pattern.finditer(func_text):
                schema = match.group(1) or None
                sp_name = match.group(2)
                if not _is_valid_sp_name(sp_name):
                    continue
                results.append({
                    "name": sp_name,
                    "schema": schema,
                    "source_file": file_path,
                    "source_line": func_node.start_point[0] + 1,
                    "function_name": func_name,
                    "file": file_path,
                    "type": "stored_procedure",
                })

            # CActiveRecord: ClassName::model()
            for match in ar_pattern.finditer(func_text):
                class_name_ar = match.group(1)
                if class_name_ar.upper() in ('PARENT', 'SELF', 'STATIC'):
                    continue
                results.append({
                    "name": class_name_ar,
                    "schema": None,
                    "source_file": file_path,
                    "source_line": func_node.start_point[0] + 1,
                    "function_name": func_name,
                    "file": file_path,
                    "type": "table",
                })

        # tableName() method outside functions
        for match in tablename_pattern.finditer(source_str):
            table_name = match.group(1).strip('{}')
            if not table_name or not is_valid_table_name(table_name.split('.')[-1]):
                continue
            already_found = any(t["name"] == table_name for t in results)
            if already_found:
                continue
            line_no = source_str[:match.start()].count("\n") + 1
            results.append({
                "name": table_name,
                "schema": None,
                "source_file": file_path,
                "source_line": line_no,
                "function_name": None,
                "file": file_path,
                "type": "table",
            })

        # Also search outside functions — resolve enclosing function by byte position
        # Precompute char→byte mapping for accurate position comparison
        def char_to_byte(pos: int) -> int:
            return len(source_str[:pos].encode('utf-8'))

        for match in TABLE_PATTERN.finditer(source_str):
            table_name = match.group(1) or match.group(2)
            if not table_name:
                continue
            if not is_valid_table_name(table_name):
                continue
            already_found = any(t["name"] == table_name for t in results)
            if already_found:
                continue

            # Check context around match — must look like SQL
            ctx_start = max(0, match.start() - 200)
            ctx_end = min(len(source_str), match.end() + 200)
            context = source_str[ctx_start:ctx_end]
            if not looks_like_sql(context):
                continue

            byte_pos = char_to_byte(match.start())
            func_name = None
            func_line = 0
            for func_node, _ in func_entries:
                if func_node.start_byte <= byte_pos <= func_node.end_byte:
                    fn_node = func_node.child_by_field_name("name")
                    if fn_node:
                        func_name = fn_node.text.decode("utf-8", errors="replace")
                        func_line = func_node.start_point[0] + 1
                    break

            results.append({
                "name": table_name,
                "schema": None,
                "source_file": file_path,
                "source_line": func_line,
                "function_name": func_name,
                "file": file_path,
                "type": "table",
            })

        for match in sp_pattern.finditer(source_str):
            schema = match.group(1) or None
            sp_name = match.group(2)
            if not _is_valid_sp_name(sp_name):
                continue
            already_found = any(t["name"] == sp_name and t.get("schema") == schema for t in results)
            if already_found:
                continue

            byte_pos = char_to_byte(match.start())
            func_name = None
            func_line = 0
            for func_node, _ in func_entries:
                if func_node.start_byte <= byte_pos <= func_node.end_byte:
                    fn_node = func_node.child_by_field_name("name")
                    if fn_node:
                        func_name = fn_node.text.decode("utf-8", errors="replace")
                        func_line = func_node.start_point[0] + 1
                    break

            results.append({
                "name": sp_name,
                "schema": schema,
                "source_file": file_path,
                "source_line": func_line,
                "function_name": func_name,
                "file": file_path,
                "type": "stored_procedure",
            })

        for match in call_pattern.finditer(source_str):
            schema = match.group(1) or None
            sp_name = match.group(2)
            if not _is_valid_sp_name(sp_name):
                continue
            already_found = any(t["name"] == sp_name and t.get("schema") == schema for t in results)
            if already_found:
                continue

            byte_pos = char_to_byte(match.start())
            func_name = None
            func_line = 0
            for func_node, _ in func_entries:
                if func_node.start_byte <= byte_pos <= func_node.end_byte:
                    fn_node = func_node.child_by_field_name("name")
                    if fn_node:
                        func_name = fn_node.text.decode("utf-8", errors="replace")
                        func_line = func_node.start_point[0] + 1
                    break

            results.append({
                "name": sp_name,
                "schema": schema,
                "source_file": file_path,
                "source_line": func_line,
                "function_name": func_name,
                "file": file_path,
                "type": "stored_procedure",
            })

        return results

    def _extract_endpoints(self, root: Node, file_path: str, source: bytes) -> list[dict]:
        """Extract endpoints: annotations > config > convention."""
        source_str = source.decode("utf-8", errors="replace")
        results = []
        seen = set()  # deduplicate by (route, handler_method)
        func_entries = self._get_all_function_entries(root)

        # Level 1: Annotation-based — scan doc comments for route annotations
        route_annotations = [
            re.compile(r'@Route\s*\(\s*(?:path\s*=\s*)?["\']([^"\']+)["\']', re.IGNORECASE),
            re.compile(r'@(Get|Post|Put|Delete|Patch|Options)\s*\(\s*(?:path\s*=\s*)?["\']([^"\']+)["\']', re.IGNORECASE),
            re.compile(r'@RequestMapping\s*\(\s*(?:value\s*=\s*)?["\']([^"\']+)["\']', re.IGNORECASE),
        ]

        for func_node, class_name in func_entries:
            name_node = func_node.child_by_field_name("name")
            if not name_node:
                continue
            func_name = name_node.text.decode("utf-8", errors="replace")

            # Get preceding doc comment
            prev = func_node.prev_named_sibling
            if prev and prev.type == "comment":
                comment_text = source_str[prev.start_byte:prev.end_byte]
                for pattern in route_annotations:
                    match = pattern.search(comment_text)
                    if match:
                        route = match.group(1) if match.lastindex == 1 else match.group(2)
                        http_method = match.group(1).upper() if pattern is route_annotations[1] else None
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
                        break

        # Level 2: Config-based — Yii urlManager rules
        if "urlManager" in source_str:
            url_rule_pattern = re.compile(r"""['"]([^'"]+)['"]\s*=>\s*['"](\w+)/(\w+)['"]""")
            for match in url_rule_pattern.finditer(source_str):
                route_pattern, controller, action = match.group(1), match.group(2), match.group(3)
                # Validate: controller must look like a real controller name (PascalCase, 3+ chars)
                if len(controller) < 3 or not re.match(r'^[A-Z][a-zA-Z]+$', controller):
                    continue
                if len(action) < 2 or not re.match(r'^[a-z][a-zA-Z]+$', action):
                    continue
                key = (route_pattern, action)
                if key not in seen:
                    seen.add(key)
                    results.append({
                        "name": route_pattern,
                        "route": route_pattern,
                        "handler_method": "action" + action[0].upper() + action[1:],
                        "handler_class": controller + "Controller",
                        "file": file_path,
                        "line": source_str[:match.start()].count("\n") + 1,
                        "type": "config",
                        "http_method": None,
                    })

        # Level 3: Convention-based — action* methods (fallback)
        for func_node, class_name in func_entries:
            name_node = func_node.child_by_field_name("name")
            if not name_node:
                continue

            func_name = name_node.text.decode("utf-8", errors="replace")
            if not func_name.startswith("action"):
                continue

            action_name = func_name[6:]
            endpoint_name = re.sub(r"(?<!^)(?=[A-Z])", "-", action_name).lower()

            # Derive HTTP method from action prefix or function body
            func_text = source_str[func_node.start_byte:func_node.end_byte]
            if action_name.startswith("Get"):
                http_method = "GET"
            elif action_name.startswith("Post"):
                http_method = "POST"
            elif action_name.startswith("Put"):
                http_method = "PUT"
            elif action_name.startswith("Delete"):
                http_method = "DELETE"
            elif action_name.startswith("Patch"):
                http_method = "PATCH"
            elif "$_POST" in func_text or "isPostRequest" in func_text or "isMethod('POST')" in func_text:
                http_method = "POST"
            elif "$_GET" in func_text or "isGetRequest" in func_text or "isMethod('GET')" in func_text:
                http_method = "GET"
            else:
                http_method = "ANY"

            controller = class_name.replace("Controller", "") if class_name else None
            if controller:
                controller_kebab = re.sub(r"(?<!^)(?=[A-Z])", "-", controller).lower()
                route = controller_kebab + "/" + endpoint_name
            else:
                route = endpoint_name

            key = (route, func_name)
            if key not in seen:
                seen.add(key)
                results.append({
                    "name": endpoint_name,
                    "route": route,
                    "handler_method": func_name,
                    "handler_class": class_name,
                    "file": file_path,
                    "line": func_node.start_point[0] + 1,
                    "type": "console" if class_name and "Command" in class_name else "convention",
                    "http_method": http_method,
                })

        return results

    def _extract_external_services(self, root: Node, file_path: str, source: bytes) -> list[dict]:
        """Detect external service calls: $recrsClient->post(), RecsysClient::send(), etc."""
        source_str = source.decode("utf-8", errors="replace")
        results = []

        # Resolve $this->property to actual class type via constructor
        prop_map = {}
        for m in re.finditer(r'\$this->(\w+)\s*=\s*new\s+\\?(\w+)', source_str):
            prop_map[m.group(1)] = m.group(2)
        for m in re.finditer(r'/\*\*\s*@var\s+(\w+)\s+\$(\w+)', source_str):
            prop_map[m.group(2)] = m.group(1)

        # Internal class names for filtering (case-insensitive for camelCase/PascalCase match)
        file_class_names_lower = set()
        for node in self._find_all(root, "class_declaration"):
            name_node = node.child_by_field_name("name")
            if name_node:
                file_class_names_lower.add(name_node.text.decode("utf-8", errors="replace").lower())

        # Instance calls: only match variables with service-like suffixes
        client_pattern = re.compile(
            r"\$(\w*(?:Client|Service|Api|Gateway|Provider|Adapter|Manager|Handler|Connection))\s*->\s*(\w+)\s*\(",
            re.IGNORECASE,
        )
        # Static calls: match classes with service-like suffixes
        static_pattern = re.compile(
            r"(\w+(?:Client|Service|Api|Gateway|Provider|Adapter|Manager|Handler|Connection|DB))\s*::\s*(\w+)\s*\(",
        )
        # Chained calls: $this->client->method()
        member_client_pattern = re.compile(
            r"\$this\s*->\s*(\w*(?:client|service|api|gateway|provider|adapter))\s*->\s*(\w+)\s*\(",
            re.IGNORECASE,
        )

        func_entries = self._get_all_function_entries(root)

        for func_node, class_name in func_entries:
            func_name_node = func_node.child_by_field_name("name")
            if not func_name_node:
                continue

            func_text = source_str[func_node.start_byte:func_node.end_byte]
            func_name = func_name_node.text.decode("utf-8", errors="replace")

            for match in client_pattern.finditer(func_text):
                var_name = match.group(1)
                method = match.group(2)
                if method.startswith("__"):
                    continue
                if len(var_name) < 3:
                    continue
                results.append({
                    "service_var": var_name,
                    "service_class": None,
                    "method": method,
                    "function_name": func_name,
                    "file": file_path,
                    "line": func_node.start_point[0] + 1,
                })

            for match in static_pattern.finditer(func_text):
                svc_class = match.group(1)
                method = match.group(2)
                if len(svc_class) < 3:
                    continue
                results.append({
                    "service_var": None,
                    "service_class": svc_class,
                    "method": method,
                    "function_name": func_name,
                    "file": file_path,
                    "line": func_node.start_point[0] + 1,
                })

            for match in member_client_pattern.finditer(func_text):
                prop_name = match.group(1)
                method = match.group(2)
                if method.startswith("__"):
                    continue

                # Resolve property to actual class type
                resolved_name = prop_map.get(prop_name, prop_name)
                was_resolved = prop_name in prop_map

                # For unresolved generic names — use enclosing class as identity
                if not was_resolved and prop_name.lower() in ('client', 'service', 'api', 'connection', 'adapter'):
                    if class_name:
                        resolved_name = class_name

                # Skip internal DI services (project class with Service suffix, case-insensitive)
                if resolved_name.lower() in file_class_names_lower and resolved_name.lower().endswith("service"):
                    continue
                # Skip short names — not real services ($s, $p)
                if len(resolved_name) < 3:
                    continue

                results.append({
                    "service_var": resolved_name,
                    "service_class": None,
                    "method": method,
                    "function_name": func_name,
                    "file": file_path,
                    "line": func_node.start_point[0] + 1,
                })

        return results

    def _extract_framework_usage(self, root: Node, file_path: str, source: bytes) -> list[dict]:
        """Detect Yii framework patterns: Yii::app()->db, Yii::import(), etc."""
        source_str = source.decode("utf-8", errors="replace")
        results = []

        yii_component = re.compile(r"Yii::app\(\)\s*->\s*(\w+)")
        yii_import = re.compile(r"Yii::import\s*\(\s*['\"]([^'\"]+)['\"]")
        yii_params = re.compile(r"Yii::app\(\)\s*->\s*params\s*\[\s*['\"](\w+)['\"]\s*\]")
        yii_static = re.compile(r"Yii::\s*(\w+)\s*\(")
        yii_db_method = re.compile(
            r"->\s*(createCommand|queryAll|queryRow|queryColumn|execute|queryScalar)\s*\("
        )

        func_entries = self._get_all_function_entries(root)

        for func_node, class_name in func_entries:
            func_name_node = func_node.child_by_field_name("name")
            if not func_name_node:
                continue

            func_text = source_str[func_node.start_byte:func_node.end_byte]
            func_name = func_name_node.text.decode("utf-8", errors="replace")

            for match in yii_component.finditer(func_text):
                component = match.group(1)
                comp_type = "db" if component.startswith("db") else \
                           "cache" if "cache" in component.lower() else \
                           "search" if "search" in component.lower() or "sphinx" in component.lower() else \
                           "component"
                results.append({
                    "framework": "Yii",
                    "pattern": "component",
                    "name": component,
                    "type": comp_type,
                    "function_name": func_name,
                    "file": file_path,
                    "line": func_node.start_point[0] + 1,
                })

            for match in yii_import.finditer(func_text):
                results.append({
                    "framework": "Yii",
                    "pattern": "import",
                    "name": match.group(1),
                    "type": "import",
                    "function_name": func_name,
                    "file": file_path,
                    "line": func_node.start_point[0] + 1,
                })

            for match in yii_params.finditer(func_text):
                results.append({
                    "framework": "Yii",
                    "pattern": "params",
                    "name": match.group(1),
                    "type": "config",
                    "function_name": func_name,
                    "file": file_path,
                    "line": func_node.start_point[0] + 1,
                })

            for match in yii_static.finditer(func_text):
                method = match.group(1)
                if method not in ("app", "import", "getModel", "createComponent"):
                    results.append({
                        "framework": "Yii",
                        "pattern": "static",
                        "name": method,
                        "type": "static_call",
                        "function_name": func_name,
                        "file": file_path,
                        "line": func_node.start_point[0] + 1,
                    })

            for match in yii_db_method.finditer(func_text):
                method = match.group(1)
                results.append({
                    "framework": "Yii",
                    "pattern": "db_method",
                    "name": method,
                    "type": "database",
                    "function_name": func_name,
                    "file": file_path,
                    "line": func_node.start_point[0] + 1,
                })

        return results

    # Paths that are never config files
    _CONFIG_EXCLUDED_PATHS = (
        "/views/", "/templates/", "/tpl/",
        "/public/", "/web/", "/static/", "/htdocs/",
        "/migrations/", "/fixtures/", "/seeds/",
        "/tests/", "/spec/",
    )

    def _extract_php_config(self, source: bytes, file_path: str) -> list[dict]:
        """Extract config key-value pairs from PHP config files (return [...])."""
        # Filter out view templates, migrations, tests
        if any(p in file_path for p in self._CONFIG_EXCLUDED_PATHS):
            return []

        source_str = source.decode("utf-8", errors="replace")

        # Only process files that look like config (no class definitions, has return [...])
        if "class " in source_str and "function " in source_str:
            return []
        if "return" not in source_str and "=>" not in source_str:
            return []

        kv_pattern = re.compile(r"""['"](\w+)['"]\s*=>\s*['"]([^'"]+)['"]""")
        results = []
        seen = set()

        for match in kv_pattern.finditer(source_str):
            key, value = match.group(1), match.group(2)
            infra_type = _classify_entry(key, value)
            if not infra_type:
                continue
            entry_key = (key, file_path)
            if entry_key in seen:
                continue
            seen.add(entry_key)
            results.append({
                "key": key,
                "value": value,
                "type": infra_type,
                "file": file_path,
                "line": source_str[:match.start()].count("\n") + 1,
            })

        return results

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
            "config_entries": self._extract_php_config(source_code, file_path),
            "scheduled_tasks": [],
        }
