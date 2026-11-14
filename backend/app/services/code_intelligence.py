import importlib
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from tree_sitter import Language, Node, Parser

logger = logging.getLogger("orchestrix.intelligence")


# -----------------------------------------------------------------------------
# Common Intelligence Result Schema
# -----------------------------------------------------------------------------


@dataclass
class ExtractedSymbol:
    name: str
    symbol_type: str  # function, class, method, interface, struct, enum, trait, module, namespace
    start_line: int  # 1-indexed
    end_line: int  # 1-indexed
    start_column: int  # 0-indexed
    end_column: int  # 0-indexed
    signature: str | None = None
    parent_symbol_name: str | None = None


@dataclass
class ExtractedImport:
    module_name: str
    is_external: bool = True
    raw_statement: str | None = None


@dataclass
class FileIntelligence:
    language: str
    line_count: int
    symbols: list[ExtractedSymbol] = field(default_factory=list)
    imports: list[ExtractedImport] = field(default_factory=list)
    parse_error: str | None = None


# -----------------------------------------------------------------------------
# Extraction Helpers
# -----------------------------------------------------------------------------


def _get_node_text(node: Node | None, source_bytes: bytes) -> str:
    """Extract decoded text of a node safely."""
    if node is None:
        return ""
    return source_bytes[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _get_first_line(text: str) -> str:
    """Extract clean first line for symbol signatures."""
    lines = text.strip().splitlines()
    if not lines:
        return ""
    first = lines[0].strip()
    return first.rstrip("{").rstrip(":").strip()


# -----------------------------------------------------------------------------
# Language Extraction Adapter Interface
# -----------------------------------------------------------------------------


class BaseLanguageAdapter(ABC):
    """Common interface for language-specific AST symbol and dependency extraction."""

    @abstractmethod
    def extract(
        self, root: Node, source_bytes: bytes
    ) -> tuple[list[ExtractedSymbol], list[ExtractedImport]]:
        """Extract code symbols and import statements from AST root."""
        pass


# -----------------------------------------------------------------------------
# 1. Python Adapter
# -----------------------------------------------------------------------------


class PythonAdapter(BaseLanguageAdapter):
    def extract(
        self, root: Node, source_bytes: bytes
    ) -> tuple[list[ExtractedSymbol], list[ExtractedImport]]:
        symbols: list[ExtractedSymbol] = []
        imports: list[ExtractedImport] = []

        def _traverse(node: Node, parent_class: str | None = None) -> None:
            if node.type == "class_definition":
                name_node = node.child_by_field_name("name")
                class_name = _get_node_text(name_node, source_bytes) if name_node else None
                if class_name:
                    sig = _get_first_line(_get_node_text(node, source_bytes))
                    symbols.append(
                        ExtractedSymbol(
                            name=class_name,
                            symbol_type="class",
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=sig,
                            parent_symbol_name=parent_class,
                        )
                    )
                    body = node.child_by_field_name("body")
                    if body:
                        for child in body.children:
                            _traverse(child, parent_class=class_name)
                    return

            if node.type in ("function_definition", "async_function_definition"):
                name_node = node.child_by_field_name("name")
                func_name = _get_node_text(name_node, source_bytes) if name_node else None
                if func_name:
                    sig = _get_first_line(_get_node_text(node, source_bytes))
                    symbols.append(
                        ExtractedSymbol(
                            name=func_name,
                            symbol_type="method" if parent_class else "function",
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=sig,
                            parent_symbol_name=parent_class,
                        )
                    )
                    body = node.child_by_field_name("body")
                    if body:
                        for child in body.children:
                            _traverse(child, parent_class=parent_class)
                    return

            if node.type in ("import_statement", "import_from_statement"):
                raw = _get_node_text(node, source_bytes).strip()
                if node.type == "import_statement":
                    for child in node.children:
                        if child.type == "dotted_name":
                            mod = _get_node_text(child, source_bytes)
                            imports.append(ExtractedImport(module_name=mod, raw_statement=raw))
                elif node.type == "import_from_statement":
                    mod_node = node.child_by_field_name("module_name")
                    mod = _get_node_text(mod_node, source_bytes) if mod_node else "unknown"
                    imports.append(ExtractedImport(module_name=mod, raw_statement=raw))
                return

            for child in node.children:
                _traverse(child, parent_class=parent_class)

        _traverse(root)
        return symbols, imports


# -----------------------------------------------------------------------------
# 2. JavaScript / TypeScript / TSX / JSX Adapter
# -----------------------------------------------------------------------------


class JavaScriptFamilyAdapter(BaseLanguageAdapter):
    def extract(
        self, root: Node, source_bytes: bytes
    ) -> tuple[list[ExtractedSymbol], list[ExtractedImport]]:
        symbols: list[ExtractedSymbol] = []
        imports: list[ExtractedImport] = []

        def _traverse(node: Node, parent_class: str | None = None) -> None:
            actual_node = node
            if node.type == "export_statement":
                dec = node.child_by_field_name("declaration")
                if dec:
                    actual_node = dec

            if actual_node.type in ("class_declaration", "class"):
                name_node = actual_node.child_by_field_name("name")
                class_name = _get_node_text(name_node, source_bytes) if name_node else None
                if class_name:
                    sig = _get_first_line(_get_node_text(actual_node, source_bytes))
                    symbols.append(
                        ExtractedSymbol(
                            name=class_name,
                            symbol_type="class",
                            start_line=actual_node.start_point.row + 1,
                            end_line=actual_node.end_point.row + 1,
                            start_column=actual_node.start_point.column,
                            end_column=actual_node.end_point.column,
                            signature=sig,
                            parent_symbol_name=parent_class,
                        )
                    )
                    body = actual_node.child_by_field_name("body")
                    if body:
                        for child in body.children:
                            _traverse(child, parent_class=class_name)
                    return

            if actual_node.type == "interface_declaration":
                name_node = actual_node.child_by_field_name("name")
                iface_name = _get_node_text(name_node, source_bytes) if name_node else None
                if iface_name:
                    symbols.append(
                        ExtractedSymbol(
                            name=iface_name,
                            symbol_type="interface",
                            start_line=actual_node.start_point.row + 1,
                            end_line=actual_node.end_point.row + 1,
                            start_column=actual_node.start_point.column,
                            end_column=actual_node.end_point.column,
                            signature=_get_first_line(_get_node_text(actual_node, source_bytes)),
                            parent_symbol_name=parent_class,
                        )
                    )
                return

            if actual_node.type == "enum_declaration":
                name_node = actual_node.child_by_field_name("name")
                enum_name = _get_node_text(name_node, source_bytes) if name_node else None
                if enum_name:
                    symbols.append(
                        ExtractedSymbol(
                            name=enum_name,
                            symbol_type="enum",
                            start_line=actual_node.start_point.row + 1,
                            end_line=actual_node.end_point.row + 1,
                            start_column=actual_node.start_point.column,
                            end_column=actual_node.end_point.column,
                            signature=_get_first_line(_get_node_text(actual_node, source_bytes)),
                            parent_symbol_name=parent_class,
                        )
                    )
                return

            if actual_node.type in (
                "function_declaration",
                "method_definition",
                "generator_function_declaration",
            ):
                name_node = actual_node.child_by_field_name("name")
                func_name = _get_node_text(name_node, source_bytes) if name_node else None
                if func_name:
                    sig = _get_first_line(_get_node_text(actual_node, source_bytes))
                    symbols.append(
                        ExtractedSymbol(
                            name=func_name,
                            symbol_type="method" if parent_class else "function",
                            start_line=actual_node.start_point.row + 1,
                            end_line=actual_node.end_point.row + 1,
                            start_column=actual_node.start_point.column,
                            end_column=actual_node.end_point.column,
                            signature=sig,
                            parent_symbol_name=parent_class,
                        )
                    )
                    body = actual_node.child_by_field_name("body")
                    if body:
                        for child in body.children:
                            _traverse(child, parent_class=parent_class)
                    return

            if actual_node.type == "import_statement":
                src = actual_node.child_by_field_name("source")
                if src:
                    mod = _get_node_text(src, source_bytes).strip("\"'")
                    imports.append(
                        ExtractedImport(
                            module_name=mod,
                            is_external=not mod.startswith("."),
                            raw_statement=_get_node_text(actual_node, source_bytes),
                        )
                    )
                return

            for child in actual_node.children:
                _traverse(child, parent_class=parent_class)

        _traverse(root)
        return symbols, imports


# -----------------------------------------------------------------------------
# 3. Java / Kotlin Adapter
# -----------------------------------------------------------------------------


class JavaFamilyAdapter(BaseLanguageAdapter):
    def extract(
        self, root: Node, source_bytes: bytes
    ) -> tuple[list[ExtractedSymbol], list[ExtractedImport]]:
        symbols: list[ExtractedSymbol] = []
        imports: list[ExtractedImport] = []

        def _traverse(node: Node, parent_class: str | None = None) -> None:
            if node.type in ("class_declaration", "interface_declaration", "enum_declaration"):
                name_node = node.child_by_field_name("name")
                class_name = _get_node_text(name_node, source_bytes) if name_node else None
                if class_name:
                    stype = (
                        "interface"
                        if "interface" in node.type
                        else "enum"
                        if "enum" in node.type
                        else "class"
                    )
                    symbols.append(
                        ExtractedSymbol(
                            name=class_name,
                            symbol_type=stype,
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=_get_first_line(_get_node_text(node, source_bytes)),
                            parent_symbol_name=parent_class,
                        )
                    )
                    body = node.child_by_field_name("body")
                    if body:
                        for child in body.children:
                            _traverse(child, parent_class=class_name)
                    return

            if node.type in (
                "method_declaration",
                "constructor_declaration",
                "function_declaration",
            ):
                name_node = node.child_by_field_name("name")
                method_name = _get_node_text(name_node, source_bytes) if name_node else None
                if method_name:
                    symbols.append(
                        ExtractedSymbol(
                            name=method_name,
                            symbol_type="method" if parent_class else "function",
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=_get_first_line(_get_node_text(node, source_bytes)),
                            parent_symbol_name=parent_class,
                        )
                    )
                    return

            if node.type in ("import_declaration", "import"):
                text = (
                    _get_node_text(node, source_bytes)
                    .replace("import", "")
                    .replace("static", "")
                    .replace(";", "")
                    .strip()
                )
                if text:
                    imports.append(
                        ExtractedImport(
                            module_name=text, raw_statement=_get_node_text(node, source_bytes)
                        )
                    )
                return

            for child in node.children:
                _traverse(child, parent_class=parent_class)

        _traverse(root)
        return symbols, imports


# -----------------------------------------------------------------------------
# 4. C / C++ Adapter
# -----------------------------------------------------------------------------


class CFamilyAdapter(BaseLanguageAdapter):
    def extract(
        self, root: Node, source_bytes: bytes
    ) -> tuple[list[ExtractedSymbol], list[ExtractedImport]]:
        symbols: list[ExtractedSymbol] = []
        imports: list[ExtractedImport] = []

        def _find_id(dec_node: Node) -> str | None:
            if dec_node.type in ("identifier", "field_identifier"):
                return _get_node_text(dec_node, source_bytes)
            for child in dec_node.children:
                found = _find_id(child)
                if found:
                    return found
            return None

        def _traverse(node: Node, parent_class: str | None = None) -> None:
            if node.type in ("class_specifier", "struct_specifier"):
                name_node = node.child_by_field_name("name")
                c_name = _get_node_text(name_node, source_bytes) if name_node else None
                if c_name:
                    symbols.append(
                        ExtractedSymbol(
                            name=c_name,
                            symbol_type="struct" if "struct" in node.type else "class",
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=_get_first_line(_get_node_text(node, source_bytes)),
                            parent_symbol_name=parent_class,
                        )
                    )
                    body = node.child_by_field_name("body")
                    if body:
                        for child in body.children:
                            _traverse(child, parent_class=c_name)
                    return

            if node.type == "function_definition":
                dec = node.child_by_field_name("declarator")
                if dec:
                    f_name = _find_id(dec)
                    if f_name:
                        symbols.append(
                            ExtractedSymbol(
                                name=f_name,
                                symbol_type="method" if parent_class else "function",
                                start_line=node.start_point.row + 1,
                                end_line=node.end_point.row + 1,
                                start_column=node.start_point.column,
                                end_column=node.end_point.column,
                                signature=_get_first_line(_get_node_text(node, source_bytes)),
                                parent_symbol_name=parent_class,
                            )
                        )
                        return

            if node.type == "preproc_include":
                path_node = node.child_by_field_name("path")
                if path_node:
                    inc_path = _get_node_text(path_node, source_bytes).strip("<>\"'")
                    imports.append(
                        ExtractedImport(
                            module_name=inc_path, raw_statement=_get_node_text(node, source_bytes)
                        )
                    )
                return

            for child in node.children:
                _traverse(child, parent_class=parent_class)

        _traverse(root)
        return symbols, imports


# -----------------------------------------------------------------------------
# 5. Go Adapter
# -----------------------------------------------------------------------------


class GoAdapter(BaseLanguageAdapter):
    def extract(
        self, root: Node, source_bytes: bytes
    ) -> tuple[list[ExtractedSymbol], list[ExtractedImport]]:
        symbols: list[ExtractedSymbol] = []
        imports: list[ExtractedImport] = []

        for node in root.children:
            if node.type == "type_declaration":
                # type Name struct / interface
                for spec in node.children:
                    if spec.type == "type_spec":
                        name_node = spec.child_by_field_name("name")
                        type_node = spec.child_by_field_name("type")
                        t_name = _get_node_text(name_node, source_bytes) if name_node else None
                        t_kind = _get_node_text(type_node, source_bytes) if type_node else ""
                        stype = "interface" if "interface" in t_kind else "struct"
                        if t_name:
                            symbols.append(
                                ExtractedSymbol(
                                    name=t_name,
                                    symbol_type=stype,
                                    start_line=spec.start_point.row + 1,
                                    end_line=spec.end_point.row + 1,
                                    start_column=spec.start_point.column,
                                    end_column=spec.end_point.column,
                                    signature=_get_first_line(_get_node_text(spec, source_bytes)),
                                )
                            )

            elif node.type == "function_declaration":
                name_node = node.child_by_field_name("name")
                f_name = _get_node_text(name_node, source_bytes) if name_node else None
                if f_name:
                    symbols.append(
                        ExtractedSymbol(
                            name=f_name,
                            symbol_type="function",
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=_get_first_line(_get_node_text(node, source_bytes)),
                        )
                    )

            elif node.type == "method_declaration":
                name_node = node.child_by_field_name("name")
                receiver_node = node.child_by_field_name("receiver")
                m_name = _get_node_text(name_node, source_bytes) if name_node else None
                rec_text = _get_node_text(receiver_node, source_bytes) if receiver_node else None
                if m_name:
                    symbols.append(
                        ExtractedSymbol(
                            name=m_name,
                            symbol_type="method",
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=_get_first_line(_get_node_text(node, source_bytes)),
                            parent_symbol_name=rec_text,
                        )
                    )

            elif node.type == "import_declaration":
                for spec in node.children:
                    if spec.type == "import_spec":
                        path_node = spec.child_by_field_name("path")
                        if path_node:
                            mod = _get_node_text(path_node, source_bytes).strip("\"'")
                            imports.append(
                                ExtractedImport(
                                    module_name=mod,
                                    raw_statement=_get_node_text(spec, source_bytes),
                                )
                            )
                    elif spec.type == "import_spec_list":
                        for sub in spec.children:
                            if sub.type == "import_spec":
                                p_node = sub.child_by_field_name("path")
                                if p_node:
                                    mod = _get_node_text(p_node, source_bytes).strip("\"'")
                                    imports.append(
                                        ExtractedImport(
                                            module_name=mod,
                                            raw_statement=_get_node_text(sub, source_bytes),
                                        )
                                    )

        return symbols, imports


# -----------------------------------------------------------------------------
# 6. Rust Adapter
# -----------------------------------------------------------------------------


class RustAdapter(BaseLanguageAdapter):
    def extract(
        self, root: Node, source_bytes: bytes
    ) -> tuple[list[ExtractedSymbol], list[ExtractedImport]]:
        symbols: list[ExtractedSymbol] = []
        imports: list[ExtractedImport] = []

        for node in root.children:
            if node.type in ("struct_item", "enum_item", "trait_item"):
                name_node = node.child_by_field_name("name")
                item_name = _get_node_text(name_node, source_bytes) if name_node else None
                if item_name:
                    stype = (
                        "struct"
                        if "struct" in node.type
                        else "enum"
                        if "enum" in node.type
                        else "trait"
                    )
                    symbols.append(
                        ExtractedSymbol(
                            name=item_name,
                            symbol_type=stype,
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=_get_first_line(_get_node_text(node, source_bytes)),
                        )
                    )

            elif node.type == "impl_item":
                # Extract methods inside impl block
                type_node = node.child_by_field_name("type")
                impl_name = _get_node_text(type_node, source_bytes) if type_node else "impl"
                body = node.child_by_field_name("body")
                if body:
                    for child in body.children:
                        if child.type == "function_item":
                            fn_name_node = child.child_by_field_name("name")
                            fn_name = (
                                _get_node_text(fn_name_node, source_bytes) if fn_name_node else None
                            )
                            if fn_name:
                                symbols.append(
                                    ExtractedSymbol(
                                        name=fn_name,
                                        symbol_type="method",
                                        start_line=child.start_point.row + 1,
                                        end_line=child.end_point.row + 1,
                                        start_column=child.start_point.column,
                                        end_column=child.end_point.column,
                                        signature=_get_first_line(
                                            _get_node_text(child, source_bytes)
                                        ),
                                        parent_symbol_name=impl_name,
                                    )
                                )

            elif node.type == "function_item":
                name_node = node.child_by_field_name("name")
                fn_name = _get_node_text(name_node, source_bytes) if name_node else None
                if fn_name:
                    symbols.append(
                        ExtractedSymbol(
                            name=fn_name,
                            symbol_type="function",
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=_get_first_line(_get_node_text(node, source_bytes)),
                        )
                    )

            elif node.type == "use_declaration":
                raw = _get_node_text(node, source_bytes)
                mod = raw.replace("use", "").replace(";", "").strip()
                imports.append(ExtractedImport(module_name=mod, raw_statement=raw))

        return symbols, imports


# -----------------------------------------------------------------------------
# 7. C# Adapter
# -----------------------------------------------------------------------------


class CSharpAdapter(BaseLanguageAdapter):
    def extract(
        self, root: Node, source_bytes: bytes
    ) -> tuple[list[ExtractedSymbol], list[ExtractedImport]]:
        symbols: list[ExtractedSymbol] = []
        imports: list[ExtractedImport] = []

        def _traverse(node: Node, parent_name: str | None = None) -> None:
            if node.type in (
                "class_declaration",
                "interface_declaration",
                "struct_declaration",
                "enum_declaration",
            ):
                name_node = node.child_by_field_name("name")
                c_name = _get_node_text(name_node, source_bytes) if name_node else None
                if c_name:
                    stype = (
                        "interface"
                        if "interface" in node.type
                        else "struct"
                        if "struct" in node.type
                        else "enum"
                        if "enum" in node.type
                        else "class"
                    )
                    symbols.append(
                        ExtractedSymbol(
                            name=c_name,
                            symbol_type=stype,
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=_get_first_line(_get_node_text(node, source_bytes)),
                            parent_symbol_name=parent_name,
                        )
                    )
                    body = node.child_by_field_name("body")
                    if body:
                        for child in body.children:
                            _traverse(child, parent_name=c_name)
                    return

            if node.type in ("method_declaration", "constructor_declaration"):
                name_node = node.child_by_field_name("name")
                m_name = _get_node_text(name_node, source_bytes) if name_node else None
                if m_name:
                    symbols.append(
                        ExtractedSymbol(
                            name=m_name,
                            symbol_type="method" if parent_name else "function",
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=_get_first_line(_get_node_text(node, source_bytes)),
                            parent_symbol_name=parent_name,
                        )
                    )
                    return

            if node.type == "using_directive":
                raw = _get_node_text(node, source_bytes)
                mod = raw.replace("using", "").replace(";", "").strip()
                imports.append(ExtractedImport(module_name=mod, raw_statement=raw))
                return

            for child in node.children:
                _traverse(child, parent_name=parent_name)

        _traverse(root)
        return symbols, imports


# -----------------------------------------------------------------------------
# 8. PHP Adapter
# -----------------------------------------------------------------------------


class PHPAdapter(BaseLanguageAdapter):
    def extract(
        self, root: Node, source_bytes: bytes
    ) -> tuple[list[ExtractedSymbol], list[ExtractedImport]]:
        symbols: list[ExtractedSymbol] = []
        imports: list[ExtractedImport] = []

        def _traverse(node: Node, parent_class: str | None = None) -> None:
            if node.type in ("class_declaration", "interface_declaration", "trait_declaration"):
                name_node = node.child_by_field_name("name")
                c_name = _get_node_text(name_node, source_bytes) if name_node else None
                if c_name:
                    stype = (
                        "interface"
                        if "interface" in node.type
                        else "trait"
                        if "trait" in node.type
                        else "class"
                    )
                    symbols.append(
                        ExtractedSymbol(
                            name=c_name,
                            symbol_type=stype,
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=_get_first_line(_get_node_text(node, source_bytes)),
                            parent_symbol_name=parent_class,
                        )
                    )
                    body = node.child_by_field_name("body")
                    if body:
                        for child in body.children:
                            _traverse(child, parent_class=c_name)
                    return

            if node.type in ("function_definition", "method_declaration"):
                name_node = node.child_by_field_name("name")
                f_name = _get_node_text(name_node, source_bytes) if name_node else None
                if f_name:
                    symbols.append(
                        ExtractedSymbol(
                            name=f_name,
                            symbol_type="method" if parent_class else "function",
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=_get_first_line(_get_node_text(node, source_bytes)),
                            parent_symbol_name=parent_class,
                        )
                    )
                    return

            if node.type == "namespace_use_declaration":
                raw = _get_node_text(node, source_bytes)
                mod = raw.replace("use", "").replace(";", "").strip()
                imports.append(ExtractedImport(module_name=mod, raw_statement=raw))
                return

            for child in node.children:
                _traverse(child, parent_class=parent_class)

        _traverse(root)
        return symbols, imports


# -----------------------------------------------------------------------------
# 9. Ruby Adapter
# -----------------------------------------------------------------------------


class RubyAdapter(BaseLanguageAdapter):
    def extract(
        self, root: Node, source_bytes: bytes
    ) -> tuple[list[ExtractedSymbol], list[ExtractedImport]]:
        symbols: list[ExtractedSymbol] = []
        imports: list[ExtractedImport] = []

        def _traverse(node: Node, parent_class: str | None = None) -> None:
            if node.type in ("class", "module"):
                name_node = node.child_by_field_name("name")
                c_name = _get_node_text(name_node, source_bytes) if name_node else None
                if c_name:
                    symbols.append(
                        ExtractedSymbol(
                            name=c_name,
                            symbol_type="module" if node.type == "module" else "class",
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=_get_first_line(_get_node_text(node, source_bytes)),
                            parent_symbol_name=parent_class,
                        )
                    )
                    body = node.child_by_field_name("body")
                    if body:
                        for child in body.children:
                            _traverse(child, parent_class=c_name)
                    return

            if node.type in ("method", "singleton_method"):
                name_node = node.child_by_field_name("name")
                m_name = _get_node_text(name_node, source_bytes) if name_node else None
                if m_name:
                    symbols.append(
                        ExtractedSymbol(
                            name=m_name,
                            symbol_type="method" if parent_class else "function",
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=_get_first_line(_get_node_text(node, source_bytes)),
                            parent_symbol_name=parent_class,
                        )
                    )
                    return

            if node.type == "call":
                # require "json" or require_relative "helper"
                method_node = node.child_by_field_name("method")
                method_txt = _get_node_text(method_node, source_bytes)
                if method_txt in ("require", "require_relative", "include", "extend"):
                    args = node.child_by_field_name("arguments")
                    arg_txt = _get_node_text(args, source_bytes).strip("()\"' ")
                    imports.append(
                        ExtractedImport(
                            module_name=arg_txt, raw_statement=_get_node_text(node, source_bytes)
                        )
                    )

            for child in node.children:
                _traverse(child, parent_class=parent_class)

        _traverse(root)
        return symbols, imports


# -----------------------------------------------------------------------------
# 10. Swift Adapter
# -----------------------------------------------------------------------------


class SwiftAdapter(BaseLanguageAdapter):
    def extract(
        self, root: Node, source_bytes: bytes
    ) -> tuple[list[ExtractedSymbol], list[ExtractedImport]]:
        symbols: list[ExtractedSymbol] = []
        imports: list[ExtractedImport] = []

        def _traverse(node: Node, parent_name: str | None = None) -> None:
            if node.type in (
                "class_declaration",
                "protocol_declaration",
                "struct_declaration",
                "enum_declaration",
            ):
                name_node = node.child_by_field_name("name")
                name = _get_node_text(name_node, source_bytes) if name_node else None
                if name:
                    stype = (
                        "interface"
                        if "protocol" in node.type
                        else "struct"
                        if "struct" in node.type
                        else "enum"
                        if "enum" in node.type
                        else "class"
                    )
                    symbols.append(
                        ExtractedSymbol(
                            name=name,
                            symbol_type=stype,
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=_get_first_line(_get_node_text(node, source_bytes)),
                            parent_symbol_name=parent_name,
                        )
                    )
                    body = node.child_by_field_name("body")
                    if body:
                        for child in body.children:
                            _traverse(child, parent_name=name)
                    return

            if node.type == "function_declaration":
                name_node = node.child_by_field_name("name")
                fn_name = _get_node_text(name_node, source_bytes) if name_node else None
                if fn_name:
                    symbols.append(
                        ExtractedSymbol(
                            name=fn_name,
                            symbol_type="method" if parent_name else "function",
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=_get_first_line(_get_node_text(node, source_bytes)),
                            parent_symbol_name=parent_name,
                        )
                    )
                    return

            if node.type == "import_declaration":
                raw = _get_node_text(node, source_bytes)
                mod = raw.replace("import", "").strip()
                imports.append(ExtractedImport(module_name=mod, raw_statement=raw))
                return

            for child in node.children:
                _traverse(child, parent_name=parent_name)

        _traverse(root)
        return symbols, imports


# -----------------------------------------------------------------------------
# 11. Generic Declarative Adapter (Fallback for Scripting & Markup Languages)
# -----------------------------------------------------------------------------


class GenericDeclarationAdapter(BaseLanguageAdapter):
    """
    Robust adapter scanning common function, class, table, and import nodes across
    Lua, Bash, PowerShell, SQL, Solidity, Scala, Elixir, Haskell, Julia, Zig, etc.
    """

    def extract(
        self, root: Node, source_bytes: bytes
    ) -> tuple[list[ExtractedSymbol], list[ExtractedImport]]:
        symbols: list[ExtractedSymbol] = []
        imports: list[ExtractedImport] = []

        def _traverse(node: Node, parent_name: str | None = None) -> None:
            # Classes / Structs / Modules
            if node.type in (
                "class_definition",
                "class_declaration",
                "contract_declaration",
                "defmodule",
                "struct_definition",
                "table_definition",
                "statement",  # for SQL CREATE TABLE
            ):
                name_node = node.child_by_field_name("name")
                name = _get_node_text(name_node, source_bytes) if name_node else None
                raw = _get_node_text(node, source_bytes)
                if not name and "CREATE TABLE" in raw.upper():
                    tokens = raw.split()
                    if len(tokens) >= 3:
                        name = tokens[2].strip("();\"'`")

                if name:
                    stype = "class"
                    if "contract" in node.type:
                        stype = "class"
                    elif "struct" in node.type or "TABLE" in raw.upper():
                        stype = "struct"
                    elif "module" in node.type:
                        stype = "module"

                    symbols.append(
                        ExtractedSymbol(
                            name=name,
                            symbol_type=stype,
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=_get_first_line(raw),
                            parent_symbol_name=parent_name,
                        )
                    )

            # Functions / Methods
            elif node.type in (
                "function_declaration",
                "function_definition",
                "function_item",
                "method_definition",
                "statement_list",
            ):
                name_node = node.child_by_field_name("name")
                f_name = _get_node_text(name_node, source_bytes) if name_node else None
                raw = _get_node_text(node, source_bytes)
                # PowerShell / Bash function name detection
                if not f_name and raw.strip().startswith("function "):
                    tokens = raw.strip().split()
                    if len(tokens) >= 2:
                        f_name = tokens[1].split("(")[0].split("{")[0].strip()

                if f_name:
                    symbols.append(
                        ExtractedSymbol(
                            name=f_name,
                            symbol_type="method" if parent_name else "function",
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=_get_first_line(raw),
                            parent_symbol_name=parent_name,
                        )
                    )

            # Imports
            elif node.type in (
                "import_declaration",
                "import_directive",
                "import_or_export",
                "using_statement",
                "use_declaration",
                "imports",
            ):
                raw = _get_node_text(node, source_bytes)
                mod = raw.replace("import", "").replace(";", "").strip().strip("'\"")
                imports.append(ExtractedImport(module_name=mod, raw_statement=raw))

            # Elixir / Ruby style defmodule / def inside call
            elif node.type == "call":
                raw = _get_node_text(node, source_bytes)
                if raw.startswith("defmodule "):
                    tokens = raw.split()
                    if len(tokens) >= 2:
                        mod_name = tokens[1]
                        symbols.append(
                            ExtractedSymbol(
                                name=mod_name,
                                symbol_type="module",
                                start_line=node.start_point.row + 1,
                                end_line=node.end_point.row + 1,
                                start_column=node.start_point.column,
                                end_column=node.end_point.column,
                                signature=_get_first_line(raw),
                                parent_symbol_name=parent_name,
                            )
                        )
                elif raw.startswith("def ") or raw.startswith("defp "):
                    tokens = raw.split()
                    if len(tokens) >= 2:
                        fn_name = tokens[1].split("(")[0].strip()
                        symbols.append(
                            ExtractedSymbol(
                                name=fn_name,
                                symbol_type="function",
                                start_line=node.start_point.row + 1,
                                end_line=node.end_point.row + 1,
                                start_column=node.start_point.column,
                                end_column=node.end_point.column,
                                signature=_get_first_line(raw),
                                parent_symbol_name=parent_name,
                            )
                        )

            for child in node.children:
                _traverse(child, parent_name=parent_name)

        _traverse(root)
        return symbols, imports


# -----------------------------------------------------------------------------
# Parser Registry & Factory
# -----------------------------------------------------------------------------


@dataclass
class LanguageSpec:
    canonical_name: str
    package_name: str
    language_attr: str  # function name on module to obtain grammar pointer
    adapter: BaseLanguageAdapter
    extensions: list[str]


class ParserRegistry:
    """
    Central registry for multi-language Tree-sitter parsers, caching initialized parsers
    safely while ensuring bounded memory usage.
    """

    def __init__(self) -> None:
        self._specs: dict[str, LanguageSpec] = {}
        self._ext_map: dict[str, str] = {}
        self._parser_cache: dict[str, Parser] = {}
        self._register_default_languages()

    def register_language(self, spec: LanguageSpec) -> None:
        self._specs[spec.canonical_name] = spec
        for ext in spec.extensions:
            self._ext_map[ext.lower()] = spec.canonical_name

    def get_supported_languages(self) -> list[str]:
        return sorted(self._specs.keys())

    def get_language_spec(self, name: str) -> LanguageSpec | None:
        return self._specs.get(name)

    def get_parser(self, language_name: str) -> Parser | None:
        if language_name in self._parser_cache:
            return self._parser_cache[language_name]

        spec = self._specs.get(language_name)
        if not spec:
            return None

        try:
            mod = importlib.import_module(spec.package_name)
            fn = getattr(mod, spec.language_attr, None)
            if fn is None:
                # check alternative language getter
                fn = getattr(mod, "language", None)
            if fn is None:
                logger.warning(
                    "No language function '%s' in module %s", spec.language_attr, spec.package_name
                )
                return None

            lang = Language(fn())
            parser = Parser(lang)
            self._parser_cache[language_name] = parser
            return parser
        except Exception as exc:
            logger.warning(
                "Failed to initialize parser for %s (%s): %s", language_name, spec.package_name, exc
            )
            return None

    def _register_default_languages(self) -> None:
        # Core
        py = PythonAdapter()
        js = JavaScriptFamilyAdapter()
        java = JavaFamilyAdapter()
        c = CFamilyAdapter()
        generic = GenericDeclarationAdapter()

        self.register_language(
            LanguageSpec("Python", "tree_sitter_python", "language", py, [".py", ".pyw"])
        )
        self.register_language(
            LanguageSpec(
                "JavaScript", "tree_sitter_javascript", "language", js, [".js", ".mjs", ".cjs"]
            )
        )
        self.register_language(
            LanguageSpec(
                "TypeScript",
                "tree_sitter_typescript",
                "language_typescript",
                js,
                [".ts", ".mts", ".cts"],
            )
        )
        self.register_language(
            LanguageSpec("TSX", "tree_sitter_typescript", "language_tsx", js, [".tsx", ".jsx"])
        )
        self.register_language(
            LanguageSpec("JSX", "tree_sitter_typescript", "language_tsx", js, [".jsx"])
        )
        self.register_language(
            LanguageSpec("Java", "tree_sitter_java", "language", java, [".java"])
        )
        self.register_language(LanguageSpec("C", "tree_sitter_c", "language", c, [".c", ".h"]))
        self.register_language(
            LanguageSpec(
                "C++",
                "tree_sitter_cpp",
                "language",
                c,
                [".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx"],
            )
        )

        # Group A
        self.register_language(
            LanguageSpec("PHP", "tree_sitter_php", "language_php", PHPAdapter(), [".php", ".phtml"])
        )
        self.register_language(
            LanguageSpec("C#", "tree_sitter_c_sharp", "language", CSharpAdapter(), [".cs"])
        )
        self.register_language(
            LanguageSpec("Go", "tree_sitter_go", "language", GoAdapter(), [".go"])
        )
        self.register_language(
            LanguageSpec("Rust", "tree_sitter_rust", "language", RustAdapter(), [".rs"])
        )
        self.register_language(
            LanguageSpec("Ruby", "tree_sitter_ruby", "language", RubyAdapter(), [".rb"])
        )
        self.register_language(
            LanguageSpec("Swift", "tree_sitter_swift", "language", SwiftAdapter(), [".swift"])
        )
        self.register_language(
            LanguageSpec("Kotlin", "tree_sitter_kotlin", "language", java, [".kt", ".kts"])
        )
        self.register_language(
            LanguageSpec("Dart", "tree_sitter_dart", "language", generic, [".dart"])
        )

        # Group B
        self.register_language(
            LanguageSpec("HTML", "tree_sitter_html", "language", generic, [".html", ".htm"])
        )
        self.register_language(
            LanguageSpec("CSS", "tree_sitter_css", "language", generic, [".css", ".scss", ".sass"])
        )
        self.register_language(
            LanguageSpec("SQL", "tree_sitter_sql", "language", generic, [".sql"])
        )
        self.register_language(
            LanguageSpec("Svelte", "tree_sitter_svelte", "language", generic, [".svelte"])
        )
        self.register_language(
            LanguageSpec("YAML", "tree_sitter_yaml", "language", generic, [".yaml", ".yml"])
        )
        self.register_language(
            LanguageSpec("XML", "tree_sitter_xml", "language", generic, [".xml"])
        )
        self.register_language(
            LanguageSpec("JSON", "tree_sitter_json", "language", generic, [".json"])
        )
        self.register_language(
            LanguageSpec("TOML", "tree_sitter_toml", "language", generic, [".toml"])
        )

        # Group C
        self.register_language(
            LanguageSpec("Bash", "tree_sitter_bash", "language", generic, [".sh", ".bash", ".zsh"])
        )
        self.register_language(
            LanguageSpec(
                "PowerShell",
                "tree_sitter_powershell",
                "language",
                generic,
                [".ps1", ".psm1", ".psd1"],
            )
        )
        self.register_language(
            LanguageSpec("Lua", "tree_sitter_lua", "language", generic, [".lua"])
        )
        self.register_language(
            LanguageSpec("Scala", "tree_sitter_scala", "language", generic, [".scala", ".sc"])
        )
        self.register_language(
            LanguageSpec("Elixir", "tree_sitter_elixir", "language", generic, [".ex", ".exs"])
        )
        self.register_language(
            LanguageSpec("Haskell", "tree_sitter_haskell", "language", generic, [".hs", ".lhs"])
        )
        self.register_language(
            LanguageSpec("Perl", "tree_sitter_perl", "language", generic, [".pl", ".pm"])
        )

        # Group D & Build
        self.register_language(
            LanguageSpec("Objective-C", "tree_sitter_objc", "language", c, [".m", ".mm"])
        )
        self.register_language(
            LanguageSpec("OCaml", "tree_sitter_ocaml", "language_ocaml", generic, [".ml", ".mli"])
        )
        self.register_language(
            LanguageSpec("Julia", "tree_sitter_julia", "language", generic, [".jl"])
        )
        self.register_language(
            LanguageSpec("Zig", "tree_sitter_zig", "language", generic, [".zig"])
        )
        self.register_language(
            LanguageSpec("Solidity", "tree_sitter_solidity", "language", generic, [".sol"])
        )
        self.register_language(
            LanguageSpec("Groovy", "tree_sitter_groovy", "language", java, [".groovy", ".gvy"])
        )
        self.register_language(
            LanguageSpec(
                "Fortran",
                "tree_sitter_fortran",
                "language",
                generic,
                [".f90", ".f95", ".f03", ".for", ".f"],
            )
        )
        self.register_language(
            LanguageSpec("Pascal", "tree_sitter_pascal", "language", generic, [".pas", ".pp"])
        )
        self.register_language(
            LanguageSpec("CMake", "tree_sitter_cmake", "language", generic, [".cmake"])
        )
        self.register_language(
            LanguageSpec(
                "Make", "tree_sitter_make", "language", generic, ["makefile", "gnumakefile"]
            )
        )
        self.register_language(
            LanguageSpec(
                "Markdown", "tree_sitter_markdown", "language", generic, [".md", ".markdown"]
            )
        )


# Global Registry Singleton
PARSER_REGISTRY = ParserRegistry()


# -----------------------------------------------------------------------------
# Public Analysis API
# -----------------------------------------------------------------------------


def analyze_code_content(source_bytes: bytes, language: str) -> FileIntelligence:
    """
    Parse source code bytes using registered Tree-sitter parser and adapter.
    Gracefully handles unsupported languages or syntax errors.
    """
    line_count = len(source_bytes.splitlines()) if source_bytes else 0

    spec = PARSER_REGISTRY.get_language_spec(language)
    if not spec:
        return FileIntelligence(language=language, line_count=line_count)

    parser = PARSER_REGISTRY.get_parser(language)
    if not parser:
        return FileIntelligence(
            language=language,
            line_count=line_count,
            parse_error=f"Parser for {language} not available on this platform",
        )

    try:
        tree = parser.parse(source_bytes)
        root = tree.root_node

        parse_error = None
        if root.has_error:
            parse_error = "Syntax contains recoverable AST parse errors"

        symbols, imports = spec.adapter.extract(root, source_bytes)
        return FileIntelligence(
            language=language,
            line_count=line_count,
            symbols=symbols,
            imports=imports,
            parse_error=parse_error,
        )
    except Exception as exc:
        logger.warning("Failed AST extraction for %s: %s", language, exc)
        return FileIntelligence(
            language=language,
            line_count=line_count,
            parse_error=str(exc),
        )
