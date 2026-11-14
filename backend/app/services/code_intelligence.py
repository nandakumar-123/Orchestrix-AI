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
    return first.rstrip("{").rstrip(":").rstrip(";").strip()


def _dedup_and_validate(
    symbols: list[ExtractedSymbol], imports: list[ExtractedImport]
) -> tuple[list[ExtractedSymbol], list[ExtractedImport]]:
    """Ensure symbols are non-duplicate, within bounds, and have valid start/end lines."""
    seen_symbols: set[tuple[str, str, int, int]] = set()
    valid_symbols: list[ExtractedSymbol] = []

    for s in symbols:
        name = s.name.strip()
        if not name:
            continue
        key = (name, s.symbol_type, s.start_line, s.start_column)
        if key in seen_symbols:
            continue
        seen_symbols.add(key)

        start_line = max(1, s.start_line)
        end_line = max(start_line, s.end_line)
        start_col = max(0, s.start_column)
        end_col = max(start_col, s.end_column)

        sig = s.signature.strip() if s.signature else None
        if sig and len(sig) > 200:
            sig = sig[:197] + "..."

        valid_symbols.append(
            ExtractedSymbol(
                name=name,
                symbol_type=s.symbol_type,
                start_line=start_line,
                end_line=end_line,
                start_column=start_col,
                end_column=end_col,
                signature=sig,
                parent_symbol_name=s.parent_symbol_name,
            )
        )

    seen_imports: set[str] = set()
    valid_imports: list[ExtractedImport] = []
    for imp in imports:
        mod = imp.module_name.strip(" \"';")
        if not mod or mod in seen_imports:
            continue
        seen_imports.add(mod)
        is_external = imp.is_external and not (mod.startswith(".") or mod.startswith("/"))
        valid_imports.append(
            ExtractedImport(
                module_name=mod,
                is_external=is_external,
                raw_statement=imp.raw_statement,
            )
        )

    return valid_symbols, valid_imports


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
        return _dedup_and_validate(symbols, imports)


# -----------------------------------------------------------------------------
# 2. JavaScript / TypeScript / TSX Family Adapter
# -----------------------------------------------------------------------------


class JavaScriptFamilyAdapter(BaseLanguageAdapter):
    def extract(
        self, root: Node, source_bytes: bytes
    ) -> tuple[list[ExtractedSymbol], list[ExtractedImport]]:
        symbols: list[ExtractedSymbol] = []
        imports: list[ExtractedImport] = []

        def _traverse(node: Node, parent_name: str | None = None) -> None:
            if node.type in ("class_declaration", "class"):
                name_node = node.child_by_field_name("name")
                c_name = _get_node_text(name_node, source_bytes) if name_node else None
                if c_name:
                    sig = _get_first_line(_get_node_text(node, source_bytes))
                    symbols.append(
                        ExtractedSymbol(
                            name=c_name,
                            symbol_type="class",
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=sig,
                            parent_symbol_name=parent_name,
                        )
                    )
                    body = node.child_by_field_name("body")
                    if body:
                        for child in body.children:
                            _traverse(child, parent_name=c_name)
                    return

            if node.type == "interface_declaration":
                name_node = node.child_by_field_name("name")
                i_name = _get_node_text(name_node, source_bytes) if name_node else None
                if i_name:
                    sig = _get_first_line(_get_node_text(node, source_bytes))
                    symbols.append(
                        ExtractedSymbol(
                            name=i_name,
                            symbol_type="interface",
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=sig,
                            parent_symbol_name=parent_name,
                        )
                    )
                    body = node.child_by_field_name("body")
                    if body:
                        for child in body.children:
                            _traverse(child, parent_name=i_name)
                    return

            if node.type in ("function_declaration", "method_definition"):
                name_node = node.child_by_field_name("name")
                f_name = _get_node_text(name_node, source_bytes) if name_node else None
                if f_name:
                    sig = _get_first_line(_get_node_text(node, source_bytes))
                    symbols.append(
                        ExtractedSymbol(
                            name=f_name,
                            symbol_type="method" if parent_name else "function",
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=sig,
                            parent_symbol_name=parent_name,
                        )
                    )
                    body = node.child_by_field_name("body")
                    if body:
                        for child in body.children:
                            _traverse(child, parent_name=parent_name)
                    return

            if node.type in ("lexical_declaration", "variable_declaration"):
                for declarator in node.children:
                    if declarator.type == "variable_declarator":
                        name_node = declarator.child_by_field_name("name")
                        val_node = declarator.child_by_field_name("value")
                        if (
                            name_node
                            and val_node
                            and val_node.type in ("arrow_function", "function_expression")
                        ):
                            fn_name = _get_node_text(name_node, source_bytes)
                            sig = _get_first_line(_get_node_text(declarator, source_bytes))
                            symbols.append(
                                ExtractedSymbol(
                                    name=fn_name,
                                    symbol_type="method" if parent_name else "function",
                                    start_line=declarator.start_point.row + 1,
                                    end_line=declarator.end_point.row + 1,
                                    start_column=declarator.start_point.column,
                                    end_column=declarator.end_point.column,
                                    signature=sig,
                                    parent_symbol_name=parent_name,
                                )
                            )

            if node.type == "import_statement":
                raw = _get_node_text(node, source_bytes).strip()
                source_node = node.child_by_field_name("source")
                if source_node:
                    mod = _get_node_text(source_node, source_bytes).strip("'\"")
                    imports.append(ExtractedImport(module_name=mod, raw_statement=raw))
                return

            if node.type == "call_expression":
                fn_node = node.child_by_field_name("function")
                if fn_node and _get_node_text(fn_node, source_bytes) == "require":
                    args = node.child_by_field_name("arguments")
                    if args and args.children:
                        for arg in args.children:
                            if arg.type == "string":
                                mod = _get_node_text(arg, source_bytes).strip("'\"")
                                raw = _get_node_text(node, source_bytes).strip()
                                imports.append(ExtractedImport(module_name=mod, raw_statement=raw))

            for child in node.children:
                _traverse(child, parent_name=parent_name)

        _traverse(root)
        return _dedup_and_validate(symbols, imports)


# -----------------------------------------------------------------------------
# 3. Java / Groovy Adapter
# -----------------------------------------------------------------------------


class JavaFamilyAdapter(BaseLanguageAdapter):
    def extract(
        self, root: Node, source_bytes: bytes
    ) -> tuple[list[ExtractedSymbol], list[ExtractedImport]]:
        symbols: list[ExtractedSymbol] = []
        imports: list[ExtractedImport] = []

        def _traverse(node: Node, parent_name: str | None = None) -> None:
            if node.type in (
                "class_declaration",
                "interface_declaration",
                "record_declaration",
                "enum_declaration",
            ):
                name_node = node.child_by_field_name("name")
                c_name = _get_node_text(name_node, source_bytes) if name_node else None
                if c_name:
                    stype = (
                        "interface"
                        if node.type == "interface_declaration"
                        else "struct"
                        if node.type == "record_declaration"
                        else "enum"
                        if node.type == "enum_declaration"
                        else "class"
                    )
                    sig = _get_first_line(_get_node_text(node, source_bytes))
                    symbols.append(
                        ExtractedSymbol(
                            name=c_name,
                            symbol_type=stype,
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=sig,
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
                    sig = _get_first_line(_get_node_text(node, source_bytes))
                    symbols.append(
                        ExtractedSymbol(
                            name=m_name,
                            symbol_type="method" if parent_name else "function",
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=sig,
                            parent_symbol_name=parent_name,
                        )
                    )
                    return

            if node.type == "import_declaration":
                raw = _get_node_text(node, source_bytes).strip()
                mod = raw.replace("import", "").replace("static", "").rstrip(";").strip()
                imports.append(ExtractedImport(module_name=mod, raw_statement=raw))
                return

            for child in node.children:
                _traverse(child, parent_name=parent_name)

        _traverse(root)
        return _dedup_and_validate(symbols, imports)


# -----------------------------------------------------------------------------
# 4. C / C++ / Objective-C Family Adapter
# -----------------------------------------------------------------------------


class CFamilyAdapter(BaseLanguageAdapter):
    def extract(
        self, root: Node, source_bytes: bytes
    ) -> tuple[list[ExtractedSymbol], list[ExtractedImport]]:
        symbols: list[ExtractedSymbol] = []
        imports: list[ExtractedImport] = []

        def _traverse(node: Node, parent_name: str | None = None) -> None:
            if node.type in ("class_specifier", "struct_specifier", "enum_specifier"):
                name_node = node.child_by_field_name("name")
                s_name = _get_node_text(name_node, source_bytes) if name_node else None
                if s_name:
                    stype = (
                        "class"
                        if "class" in node.type
                        else "enum"
                        if "enum" in node.type
                        else "struct"
                    )
                    sig = _get_first_line(_get_node_text(node, source_bytes))
                    symbols.append(
                        ExtractedSymbol(
                            name=s_name,
                            symbol_type=stype,
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=sig,
                            parent_symbol_name=parent_name,
                        )
                    )
                    body = node.child_by_field_name("body")
                    if body:
                        for child in body.children:
                            _traverse(child, parent_name=s_name)
                    return

            if node.type == "function_definition":
                declarator = node.child_by_field_name("declarator")
                fn_name = None
                while declarator and declarator.type in (
                    "function_declarator",
                    "pointer_declarator",
                ):
                    sub = declarator.child_by_field_name("declarator")
                    if not sub:
                        ident = next(
                            (
                                c
                                for c in declarator.children
                                if c.type in ("identifier", "field_identifier")
                            ),
                            None,
                        )
                        fn_name = _get_node_text(ident, source_bytes) if ident else None
                        break
                    declarator = sub
                if not fn_name and declarator:
                    fn_name = _get_node_text(declarator, source_bytes)

                if fn_name:
                    clean_name = fn_name.split("(")[0].strip()
                    sig = _get_first_line(_get_node_text(node, source_bytes))
                    symbols.append(
                        ExtractedSymbol(
                            name=clean_name,
                            symbol_type="method" if parent_name else "function",
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=sig,
                            parent_symbol_name=parent_name,
                        )
                    )
                    return

            if node.type == "preproc_include":
                path_node = node.child_by_field_name("path")
                if path_node:
                    path_str = _get_node_text(path_node, source_bytes).strip("<>\"'")
                    raw = _get_node_text(node, source_bytes).strip()
                    imports.append(ExtractedImport(module_name=path_str, raw_statement=raw))
                return

            for child in node.children:
                _traverse(child, parent_name=parent_name)

        _traverse(root)
        return _dedup_and_validate(symbols, imports)


# -----------------------------------------------------------------------------
# 5. Go Adapter
# -----------------------------------------------------------------------------


class GoAdapter(BaseLanguageAdapter):
    def extract(
        self, root: Node, source_bytes: bytes
    ) -> tuple[list[ExtractedSymbol], list[ExtractedImport]]:
        symbols: list[ExtractedSymbol] = []
        imports: list[ExtractedImport] = []

        def _traverse(node: Node) -> None:
            if node.type == "function_declaration":
                name_node = node.child_by_field_name("name")
                f_name = _get_node_text(name_node, source_bytes) if name_node else None
                if f_name:
                    sig = _get_first_line(_get_node_text(node, source_bytes))
                    symbols.append(
                        ExtractedSymbol(
                            name=f_name,
                            symbol_type="function",
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=sig,
                        )
                    )
                    return

            if node.type == "method_declaration":
                name_node = node.child_by_field_name("name")
                m_name = _get_node_text(name_node, source_bytes) if name_node else None
                receiver_node = node.child_by_field_name("receiver")
                recv_text = (
                    _get_node_text(receiver_node, source_bytes).strip("()").split()[-1].strip("*")
                    if receiver_node
                    else None
                )
                if m_name:
                    sig = _get_first_line(_get_node_text(node, source_bytes))
                    symbols.append(
                        ExtractedSymbol(
                            name=m_name,
                            symbol_type="method",
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=sig,
                            parent_symbol_name=recv_text,
                        )
                    )
                    return

            if node.type == "type_spec":
                name_node = node.child_by_field_name("name")
                type_node = node.child_by_field_name("type")
                t_name = _get_node_text(name_node, source_bytes) if name_node else None
                if t_name and type_node:
                    stype = (
                        "interface"
                        if type_node.type == "interface_type"
                        else "struct"
                        if type_node.type == "struct_type"
                        else "class"
                    )
                    sig = _get_first_line(_get_node_text(node, source_bytes))
                    symbols.append(
                        ExtractedSymbol(
                            name=t_name,
                            symbol_type=stype,
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=sig,
                        )
                    )

            if node.type == "import_spec":
                path_node = node.child_by_field_name("path")
                if path_node:
                    mod = _get_node_text(path_node, source_bytes).strip('"')
                    raw = _get_node_text(node, source_bytes).strip()
                    imports.append(ExtractedImport(module_name=mod, raw_statement=raw))
                return

            for child in node.children:
                _traverse(child)

        _traverse(root)
        return _dedup_and_validate(symbols, imports)


# -----------------------------------------------------------------------------
# 6. Rust Adapter
# -----------------------------------------------------------------------------


class RustAdapter(BaseLanguageAdapter):
    def extract(
        self, root: Node, source_bytes: bytes
    ) -> tuple[list[ExtractedSymbol], list[ExtractedImport]]:
        symbols: list[ExtractedSymbol] = []
        imports: list[ExtractedImport] = []

        def _traverse(node: Node, parent_name: str | None = None) -> None:
            if node.type in ("struct_item", "enum_item", "trait_item", "union_item"):
                name_node = node.child_by_field_name("name")
                name = _get_node_text(name_node, source_bytes) if name_node else None
                if name:
                    stype = (
                        "trait"
                        if node.type == "trait_item"
                        else "enum"
                        if node.type == "enum_item"
                        else "struct"
                    )
                    sig = _get_first_line(_get_node_text(node, source_bytes))
                    symbols.append(
                        ExtractedSymbol(
                            name=name,
                            symbol_type=stype,
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=sig,
                            parent_symbol_name=parent_name,
                        )
                    )
                    body = node.child_by_field_name("body")
                    if body:
                        for child in body.children:
                            _traverse(child, parent_name=name)
                    return

            if node.type == "impl_item":
                type_node = node.child_by_field_name("type")
                impl_name = _get_node_text(type_node, source_bytes) if type_node else None
                body = node.child_by_field_name("body")
                if body and impl_name:
                    for child in body.children:
                        _traverse(child, parent_name=impl_name)
                return

            if node.type == "function_item":
                name_node = node.child_by_field_name("name")
                fn_name = _get_node_text(name_node, source_bytes) if name_node else None
                if fn_name:
                    sig = _get_first_line(_get_node_text(node, source_bytes))
                    symbols.append(
                        ExtractedSymbol(
                            name=fn_name,
                            symbol_type="method" if parent_name else "function",
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=sig,
                            parent_symbol_name=parent_name,
                        )
                    )
                    return

            if node.type == "use_declaration":
                raw = _get_node_text(node, source_bytes).strip()
                mod = raw.replace("pub ", "").replace("use ", "").rstrip(";").strip()
                imports.append(ExtractedImport(module_name=mod, raw_statement=raw))
                return

            for child in node.children:
                _traverse(child, parent_name=parent_name)

        _traverse(root)
        return _dedup_and_validate(symbols, imports)


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
                "record_declaration",
                "namespace_declaration",
            ):
                name_node = node.child_by_field_name("name")
                name = _get_node_text(name_node, source_bytes) if name_node else None
                if name:
                    stype = (
                        "namespace"
                        if "namespace" in node.type
                        else "interface"
                        if "interface" in node.type
                        else "struct"
                        if "struct" in node.type
                        else "enum"
                        if "enum" in node.type
                        else "class"
                    )
                    sig = _get_first_line(_get_node_text(node, source_bytes))
                    symbols.append(
                        ExtractedSymbol(
                            name=name,
                            symbol_type=stype,
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=sig,
                            parent_symbol_name=parent_name,
                        )
                    )
                    body = node.child_by_field_name("body")
                    if body:
                        for child in body.children:
                            _traverse(child, parent_name=name)
                    return

            if node.type in ("method_declaration", "constructor_declaration"):
                name_node = node.child_by_field_name("name")
                fn_name = _get_node_text(name_node, source_bytes) if name_node else None
                if fn_name:
                    sig = _get_first_line(_get_node_text(node, source_bytes))
                    symbols.append(
                        ExtractedSymbol(
                            name=fn_name,
                            symbol_type="method" if parent_name else "function",
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=sig,
                            parent_symbol_name=parent_name,
                        )
                    )
                    return

            if node.type == "using_directive":
                raw = _get_node_text(node, source_bytes).strip()
                mod = raw.replace("using", "").replace("static", "").rstrip(";").strip()
                imports.append(ExtractedImport(module_name=mod, raw_statement=raw))
                return

            for child in node.children:
                _traverse(child, parent_name=parent_name)

        _traverse(root)
        return _dedup_and_validate(symbols, imports)


# -----------------------------------------------------------------------------
# 8. PHP Adapter
# -----------------------------------------------------------------------------


class PHPAdapter(BaseLanguageAdapter):
    def extract(
        self, root: Node, source_bytes: bytes
    ) -> tuple[list[ExtractedSymbol], list[ExtractedImport]]:
        symbols: list[ExtractedSymbol] = []
        imports: list[ExtractedImport] = []

        def _traverse(node: Node, parent_name: str | None = None) -> None:
            if node.type in (
                "class_declaration",
                "interface_declaration",
                "trait_declaration",
                "enum_declaration",
                "namespace_definition",
            ):
                name_node = node.child_by_field_name("name")
                name = _get_node_text(name_node, source_bytes) if name_node else None
                if name:
                    stype = (
                        "namespace"
                        if "namespace" in node.type
                        else "interface"
                        if "interface" in node.type
                        else "trait"
                        if "trait" in node.type
                        else "enum"
                        if "enum" in node.type
                        else "class"
                    )
                    sig = _get_first_line(_get_node_text(node, source_bytes))
                    symbols.append(
                        ExtractedSymbol(
                            name=name,
                            symbol_type=stype,
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=sig,
                            parent_symbol_name=parent_name,
                        )
                    )
                    body = node.child_by_field_name("body")
                    if body:
                        for child in body.children:
                            _traverse(child, parent_name=name)
                    return

            if node.type in ("method_declaration", "function_definition"):
                name_node = node.child_by_field_name("name")
                fn_name = _get_node_text(name_node, source_bytes) if name_node else None
                if fn_name:
                    sig = _get_first_line(_get_node_text(node, source_bytes))
                    symbols.append(
                        ExtractedSymbol(
                            name=fn_name,
                            symbol_type="method" if parent_name else "function",
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=sig,
                            parent_symbol_name=parent_name,
                        )
                    )
                    return

            if node.type in ("namespace_use_declaration", "use_declaration"):
                raw = _get_node_text(node, source_bytes).strip()
                mod = raw.replace("use", "").rstrip(";").strip()
                imports.append(ExtractedImport(module_name=mod, raw_statement=raw))
                return

            for child in node.children:
                _traverse(child, parent_name=parent_name)

        _traverse(root)
        return _dedup_and_validate(symbols, imports)


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
        return _dedup_and_validate(symbols, imports)


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
                "extension_declaration",
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
        return _dedup_and_validate(symbols, imports)


# -----------------------------------------------------------------------------
# 11. Kotlin Dedicated Adapter
# -----------------------------------------------------------------------------


class KotlinAdapter(BaseLanguageAdapter):
    def extract(
        self, root: Node, source_bytes: bytes
    ) -> tuple[list[ExtractedSymbol], list[ExtractedImport]]:
        symbols: list[ExtractedSymbol] = []
        imports: list[ExtractedImport] = []

        def _traverse(node: Node, parent_name: str | None = None) -> None:
            if node.type in ("class_declaration", "object_declaration"):
                raw = _get_node_text(node, source_bytes)
                is_interface = any(
                    c.type == "interface" for c in node.children
                ) or raw.strip().startswith("interface ")
                is_enum = any(c.type == "enum" for c in node.children) or "enum class " in raw
                stype = "interface" if is_interface else "enum" if is_enum else "class"

                name_node = next((c for c in node.children if c.type == "identifier"), None)
                if not name_node:
                    name_node = node.child_by_field_name("name")
                name = _get_node_text(name_node, source_bytes) if name_node else None
                if name:
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
                    body = next((c for c in node.children if c.type == "class_body"), None)
                    if body:
                        for child in body.children:
                            _traverse(child, parent_name=name)
                    return

            if node.type == "function_declaration":
                name_node = next((c for c in node.children if c.type == "identifier"), None)
                if not name_node:
                    name_node = node.child_by_field_name("name")
                name = _get_node_text(name_node, source_bytes) if name_node else None
                if name:
                    symbols.append(
                        ExtractedSymbol(
                            name=name,
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

            if node.type in ("import", "import_header"):
                raw = _get_node_text(node, source_bytes)
                ident = next(
                    (c for c in node.children if c.type in ("qualified_identifier", "identifier")),
                    None,
                )
                mod = (
                    _get_node_text(ident, source_bytes)
                    if ident
                    else raw.replace("import", "").strip()
                )
                imports.append(ExtractedImport(module_name=mod, raw_statement=raw))
                return

            for child in node.children:
                _traverse(child, parent_name=parent_name)

        _traverse(root)
        return _dedup_and_validate(symbols, imports)


# -----------------------------------------------------------------------------
# 12. Dart Dedicated Adapter
# -----------------------------------------------------------------------------


class DartAdapter(BaseLanguageAdapter):
    def extract(
        self, root: Node, source_bytes: bytes
    ) -> tuple[list[ExtractedSymbol], list[ExtractedImport]]:
        symbols: list[ExtractedSymbol] = []
        imports: list[ExtractedImport] = []

        def _traverse(node: Node, parent_name: str | None = None) -> None:
            if node.type in (
                "class_definition",
                "mixin_declaration",
                "enum_declaration",
                "extension_declaration",
            ):
                name_node = next((c for c in node.children if c.type == "identifier"), None)
                name = _get_node_text(name_node, source_bytes) if name_node else None
                raw = _get_node_text(node, source_bytes)
                if name:
                    stype = (
                        "interface"
                        if "mixin" in node.type
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
                            signature=_get_first_line(raw),
                            parent_symbol_name=parent_name,
                        )
                    )
                    body = next(
                        (c for c in node.children if c.type in ("class_body", "enum_body")), None
                    )
                    if body:
                        for child in body.children:
                            _traverse(child, parent_name=name)
                    return

            if node.type in ("method_signature", "function_signature"):
                name_node = None
                for c in node.children:
                    if c.type == "function_signature":
                        name_node = next((ch for ch in c.children if ch.type == "identifier"), None)
                        break
                    if c.type == "identifier":
                        name_node = c
                        break
                name = _get_node_text(name_node, source_bytes) if name_node else None
                if name:
                    symbols.append(
                        ExtractedSymbol(
                            name=name,
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

            if node.type in ("import_or_export", "library_import"):
                raw = _get_node_text(node, source_bytes)
                uri = None
                for c in node.children:
                    if c.type == "library_import":
                        for sub in c.children:
                            if sub.type == "import_specification":
                                for uri_node in sub.children:
                                    if uri_node.type == "configurable_uri":
                                        uri = _get_node_text(uri_node, source_bytes).strip("'\"")
                                        break
                if not uri:
                    uri = (
                        raw.replace("import", "")
                        .replace("export", "")
                        .split(";")[0]
                        .strip()
                        .strip("'\"")
                    )
                imports.append(ExtractedImport(module_name=uri, raw_statement=raw))
                return

            for child in node.children:
                _traverse(child, parent_name=parent_name)

        _traverse(root)
        return _dedup_and_validate(symbols, imports)


# -----------------------------------------------------------------------------
# 13. Scala Dedicated Adapter
# -----------------------------------------------------------------------------


class ScalaAdapter(BaseLanguageAdapter):
    def extract(
        self, root: Node, source_bytes: bytes
    ) -> tuple[list[ExtractedSymbol], list[ExtractedImport]]:
        symbols: list[ExtractedSymbol] = []
        imports: list[ExtractedImport] = []

        def _traverse(node: Node, parent_name: str | None = None) -> None:
            if node.type in ("class_definition", "object_definition", "trait_definition"):
                name_node = node.child_by_field_name("name")
                if not name_node:
                    name_node = next((c for c in node.children if c.type == "identifier"), None)
                name = _get_node_text(name_node, source_bytes) if name_node else None
                if name:
                    stype = "interface" if "trait" in node.type else "class"
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
                    body = next(
                        (c for c in node.children if c.type in ("template_body", "class_body")),
                        None,
                    )
                    if body:
                        for child in body.children:
                            _traverse(child, parent_name=name)
                    return

            if node.type == "function_definition":
                name_node = node.child_by_field_name("name")
                if not name_node:
                    name_node = next((c for c in node.children if c.type == "identifier"), None)
                name = _get_node_text(name_node, source_bytes) if name_node else None
                if name:
                    symbols.append(
                        ExtractedSymbol(
                            name=name,
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

            if node.type in ("import_declaration", "import"):
                raw = _get_node_text(node, source_bytes)
                mod = raw.replace("import", "").strip().rstrip(";")
                imports.append(ExtractedImport(module_name=mod, raw_statement=raw))
                return

            for child in node.children:
                _traverse(child, parent_name=parent_name)

        _traverse(root)
        return _dedup_and_validate(symbols, imports)


# -----------------------------------------------------------------------------
# 14. Elixir Dedicated Adapter
# -----------------------------------------------------------------------------


class ElixirAdapter(BaseLanguageAdapter):
    def extract(
        self, root: Node, source_bytes: bytes
    ) -> tuple[list[ExtractedSymbol], list[ExtractedImport]]:
        symbols: list[ExtractedSymbol] = []
        imports: list[ExtractedImport] = []

        def _traverse(node: Node, parent_name: str | None = None) -> None:
            if node.type == "call":
                raw = _get_node_text(node, source_bytes)
                lines = raw.strip().splitlines()
                first = lines[0].strip() if lines else ""

                if first.startswith("defmodule "):
                    tokens = first.split()
                    if len(tokens) >= 2:
                        mod_name = tokens[1].strip()
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
                        for child in node.children:
                            _traverse(child, parent_name=mod_name)
                        return

                elif first.startswith(("def ", "defp ", "defmacro ")):
                    tokens = first.split()
                    if len(tokens) >= 2:
                        fn_name = tokens[1].split("(")[0].strip()
                        symbols.append(
                            ExtractedSymbol(
                                name=fn_name,
                                symbol_type="method" if parent_name else "function",
                                start_line=node.start_point.row + 1,
                                end_line=node.end_point.row + 1,
                                start_column=node.start_point.column,
                                end_column=node.end_point.column,
                                signature=_get_first_line(raw),
                                parent_symbol_name=parent_name,
                            )
                        )
                        return

                elif first.startswith(("alias ", "import ", "require ", "use ")):
                    tokens = first.split()
                    if len(tokens) >= 2:
                        mod_name = tokens[1].strip(" ,")
                        imports.append(ExtractedImport(module_name=mod_name, raw_statement=first))
                    return

            for child in node.children:
                _traverse(child, parent_name=parent_name)

        _traverse(root)
        return _dedup_and_validate(symbols, imports)


# -----------------------------------------------------------------------------
# 15. Haskell Dedicated Adapter
# -----------------------------------------------------------------------------


class HaskellAdapter(BaseLanguageAdapter):
    def extract(
        self, root: Node, source_bytes: bytes
    ) -> tuple[list[ExtractedSymbol], list[ExtractedImport]]:
        symbols: list[ExtractedSymbol] = []
        imports: list[ExtractedImport] = []

        def _traverse(node: Node, parent_name: str | None = None) -> None:
            if node.type == "header":
                mod_node = next(
                    (
                        c
                        for c in node.children
                        if c.type in ("module_id", "modid")
                        or (c.type == "module" and _get_node_text(c, source_bytes) != "module")
                    ),
                    None,
                )
                if not mod_node:
                    for c in node.children:
                        sub = next(
                            (
                                sc
                                for sc in c.children
                                if sc.type in ("module_id", "modid")
                                or (
                                    sc.type == "module"
                                    and _get_node_text(sc, source_bytes) != "module"
                                )
                            ),
                            None,
                        )
                        if sub:
                            mod_node = sub
                            break
                mod_name = _get_node_text(mod_node, source_bytes) if mod_node else None
                if not mod_name:
                    raw = (
                        _get_node_text(node, source_bytes)
                        .replace("module", "")
                        .replace("where", "")
                        .strip()
                    )
                    mod_name = raw.split()[0] if raw else None
                if mod_name:
                    symbols.append(
                        ExtractedSymbol(
                            name=mod_name,
                            symbol_type="module",
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=_get_first_line(_get_node_text(node, source_bytes)),
                            parent_symbol_name=parent_name,
                        )
                    )

            elif node.type in ("data_type", "newtype"):
                name_node = next((c for c in node.children if c.type == "name"), None)
                name = _get_node_text(name_node, source_bytes) if name_node else None
                if name:
                    symbols.append(
                        ExtractedSymbol(
                            name=name,
                            symbol_type="struct",
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=_get_first_line(_get_node_text(node, source_bytes)),
                            parent_symbol_name=parent_name,
                        )
                    )

            elif node.type == "class":
                name_node = next((c for c in node.children if c.type == "name"), None)
                name = _get_node_text(name_node, source_bytes) if name_node else None
                if name:
                    symbols.append(
                        ExtractedSymbol(
                            name=name,
                            symbol_type="interface",
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=_get_first_line(_get_node_text(node, source_bytes)),
                            parent_symbol_name=parent_name,
                        )
                    )
                    decls = next((c for c in node.children if c.type == "class_declarations"), None)
                    if decls:
                        for child in decls.children:
                            _traverse(child, parent_name=name)
                    return

            elif node.type in ("function", "signature"):
                var_node = next((c for c in node.children if c.type == "variable"), None)
                name = _get_node_text(var_node, source_bytes) if var_node else None
                if name:
                    if not any(
                        s.name == name and s.symbol_type in ("function", "method") for s in symbols
                    ):
                        symbols.append(
                            ExtractedSymbol(
                                name=name,
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

            elif node.type in ("import", "import_declaration"):
                mod_node = next((c for c in node.children if c.type == "module"), None)
                raw = _get_node_text(node, source_bytes)
                mod = (
                    _get_node_text(mod_node, source_bytes)
                    if mod_node
                    else raw.replace("import", "").strip()
                )
                imports.append(ExtractedImport(module_name=mod, raw_statement=raw))
                return

            for child in node.children:
                _traverse(child, parent_name=parent_name)

        _traverse(root)
        return _dedup_and_validate(symbols, imports)


# -----------------------------------------------------------------------------
# 16. Solidity Dedicated Adapter
# -----------------------------------------------------------------------------


class SolidityAdapter(BaseLanguageAdapter):
    def extract(
        self, root: Node, source_bytes: bytes
    ) -> tuple[list[ExtractedSymbol], list[ExtractedImport]]:
        symbols: list[ExtractedSymbol] = []
        imports: list[ExtractedImport] = []

        def _traverse(node: Node, parent_name: str | None = None) -> None:
            if node.type in (
                "contract_declaration",
                "interface_declaration",
                "library_declaration",
                "struct_declaration",
                "enum_declaration",
            ):
                name_node = node.child_by_field_name("name")
                if not name_node:
                    name_node = next((c for c in node.children if c.type == "identifier"), None)
                name = _get_node_text(name_node, source_bytes) if name_node else None
                if name:
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
                    body = next(
                        (
                            c
                            for c in node.children
                            if c.type in ("contract_body", "struct_body", "enum_body")
                        ),
                        None,
                    )
                    if body:
                        for child in body.children:
                            _traverse(child, parent_name=name)
                    return

            if node.type in ("function_definition", "modifier_definition", "event_definition"):
                name_node = node.child_by_field_name("name")
                if not name_node:
                    name_node = next((c for c in node.children if c.type == "identifier"), None)
                name = _get_node_text(name_node, source_bytes) if name_node else None
                if name:
                    symbols.append(
                        ExtractedSymbol(
                            name=name,
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

            if node.type == "import_directive":
                raw = _get_node_text(node, source_bytes)
                str_node = next((c for c in node.children if c.type == "string"), None)
                mod = (
                    _get_node_text(str_node, source_bytes).strip("\"'")
                    if str_node
                    else raw.replace("import", "").strip().rstrip(";")
                )
                imports.append(ExtractedImport(module_name=mod, raw_statement=raw))
                return

            for child in node.children:
                _traverse(child, parent_name=parent_name)

        _traverse(root)
        return _dedup_and_validate(symbols, imports)


# -----------------------------------------------------------------------------
# 17. Shell Dedicated Adapter (Bash & PowerShell)
# -----------------------------------------------------------------------------


class ShellAdapter(BaseLanguageAdapter):
    def extract(
        self, root: Node, source_bytes: bytes
    ) -> tuple[list[ExtractedSymbol], list[ExtractedImport]]:
        symbols: list[ExtractedSymbol] = []
        imports: list[ExtractedImport] = []

        def _traverse(node: Node, parent_name: str | None = None) -> None:
            # Bash function_definition
            if node.type == "function_definition":
                name_node = node.child_by_field_name("name")
                if not name_node:
                    name_node = next((c for c in node.children if c.type == "word"), None)
                name = _get_node_text(name_node, source_bytes) if name_node else None
                if name:
                    symbols.append(
                        ExtractedSymbol(
                            name=name,
                            symbol_type="function",
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=_get_first_line(_get_node_text(node, source_bytes)),
                            parent_symbol_name=parent_name,
                        )
                    )
                    return

            # Bash source / . import
            if node.type == "command":
                raw = _get_node_text(node, source_bytes).strip()
                if raw.startswith("source ") or raw.startswith(". "):
                    tokens = raw.split()
                    if len(tokens) >= 2:
                        target = tokens[1].strip("\"'")
                        imports.append(ExtractedImport(module_name=target, raw_statement=raw))

            # PowerShell function_statement & filter_statement
            if node.type in ("function_statement", "filter_statement"):
                name_node = next((c for c in node.children if c.type == "function_name"), None)
                name = _get_node_text(name_node, source_bytes) if name_node else None
                if name:
                    symbols.append(
                        ExtractedSymbol(
                            name=name,
                            symbol_type="function",
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=_get_first_line(_get_node_text(node, source_bytes)),
                            parent_symbol_name=parent_name,
                        )
                    )
                    return

            # PowerShell class_statement
            if node.type == "class_statement":
                name_node = next((c for c in node.children if c.type == "simple_name"), None)
                name = _get_node_text(name_node, source_bytes) if name_node else None
                if name:
                    symbols.append(
                        ExtractedSymbol(
                            name=name,
                            symbol_type="class",
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=_get_first_line(_get_node_text(node, source_bytes)),
                            parent_symbol_name=parent_name,
                        )
                    )
                    for child in node.children:
                        if child.type == "class_method_definition":
                            _traverse(child, parent_name=name)
                    return

            # PowerShell class_method_definition
            if node.type == "class_method_definition":
                name_node = next((c for c in node.children if c.type == "simple_name"), None)
                name = _get_node_text(name_node, source_bytes) if name_node else None
                if name:
                    symbols.append(
                        ExtractedSymbol(
                            name=name,
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

            # PowerShell Import-Module / using namespace
            if node.type in ("pipeline", "command"):
                raw = _get_node_text(node, source_bytes).strip()
                if raw.startswith("using namespace "):
                    mod = raw.replace("using namespace", "").strip()
                    imports.append(ExtractedImport(module_name=mod, raw_statement=raw))
                elif raw.startswith("Import-Module "):
                    tokens = raw.split()
                    if len(tokens) >= 2:
                        imports.append(ExtractedImport(module_name=tokens[1], raw_statement=raw))

            for child in node.children:
                _traverse(child, parent_name=parent_name)

        _traverse(root)
        return _dedup_and_validate(symbols, imports)


# -----------------------------------------------------------------------------
# 18. SQL Dedicated Adapter
# -----------------------------------------------------------------------------


class SQLAdapter(BaseLanguageAdapter):
    def extract(
        self, root: Node, source_bytes: bytes
    ) -> tuple[list[ExtractedSymbol], list[ExtractedImport]]:
        symbols: list[ExtractedSymbol] = []
        imports: list[ExtractedImport] = []

        def _traverse(node: Node) -> None:
            raw = _get_node_text(node, source_bytes).strip()
            upper_raw = raw.upper()

            if node.type in (
                "statement",
                "create_table",
                "create_view",
                "create_function",
                "create_procedure",
                "create_index",
            ) or upper_raw.startswith("CREATE "):
                stype = "struct"
                name = None

                for c in node.children:
                    if c.type in ("object_reference", "identifier", "table_name"):
                        name = _get_node_text(c, source_bytes).strip("();\"'`")
                        break

                if not name:
                    tokens = raw.split()
                    if len(tokens) >= 3:
                        kw = tokens[1].upper()
                        if kw in (
                            "TABLE",
                            "VIEW",
                            "PROCEDURE",
                            "FUNCTION",
                            "INDEX",
                            "TRIGGER",
                            "TYPE",
                        ):
                            name = tokens[2].split("(")[0].strip("();\"'`")
                            if kw in ("FUNCTION", "PROCEDURE"):
                                stype = "function"
                            else:
                                stype = "struct"

                if upper_raw.startswith("CREATE FUNCTION") or upper_raw.startswith(
                    "CREATE PROCEDURE"
                ):
                    stype = "function"

                if name and not any(
                    s.name == name and s.start_line == (node.start_point.row + 1) for s in symbols
                ):
                    symbols.append(
                        ExtractedSymbol(
                            name=name,
                            symbol_type=stype,
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=_get_first_line(raw),
                        )
                    )

            for child in node.children:
                _traverse(child)

        _traverse(root)
        return _dedup_and_validate(symbols, imports)


# -----------------------------------------------------------------------------
# 19. Lua Dedicated Adapter
# -----------------------------------------------------------------------------


class LuaAdapter(BaseLanguageAdapter):
    def extract(
        self, root: Node, source_bytes: bytes
    ) -> tuple[list[ExtractedSymbol], list[ExtractedImport]]:
        symbols: list[ExtractedSymbol] = []
        imports: list[ExtractedImport] = []

        def _traverse(node: Node, parent_name: str | None = None) -> None:
            if node.type in ("function_declaration", "local_function_declaration"):
                name_node = node.child_by_field_name("name")
                if not name_node:
                    for c in node.children:
                        if c.type in (
                            "identifier",
                            "function_name",
                            "dot_index_expression",
                            "method_index_expression",
                        ):
                            name_node = c
                            break
                name = _get_node_text(name_node, source_bytes) if name_node else None
                if name:
                    is_method = ":" in name or bool(parent_name)
                    symbols.append(
                        ExtractedSymbol(
                            name=name,
                            symbol_type="method" if is_method else "function",
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=_get_first_line(_get_node_text(node, source_bytes)),
                            parent_symbol_name=parent_name,
                        )
                    )
                    return

            if node.type == "variable_declaration":
                raw = _get_node_text(node, source_bytes).strip()
                if "require(" in raw or 'require "' in raw or "require '" in raw:
                    import re

                    match = re.search(r"require\s*\(\s*['\"]([^'\"]+)['\"]\s*\)", raw) or re.search(
                        r"require\s*['\"]([^'\"]+)['\"]", raw
                    )
                    if match:
                        imports.append(
                            ExtractedImport(module_name=match.group(1), raw_statement=raw)
                        )

            for child in node.children:
                _traverse(child, parent_name=parent_name)

        _traverse(root)
        return _dedup_and_validate(symbols, imports)


# -----------------------------------------------------------------------------
# 20. Julia Dedicated Adapter
# -----------------------------------------------------------------------------


class JuliaAdapter(BaseLanguageAdapter):
    def extract(
        self, root: Node, source_bytes: bytes
    ) -> tuple[list[ExtractedSymbol], list[ExtractedImport]]:
        symbols: list[ExtractedSymbol] = []
        imports: list[ExtractedImport] = []

        def _traverse(node: Node, parent_name: str | None = None) -> None:
            if node.type == "module_definition":
                name_node = next((c for c in node.children if c.type == "identifier"), None)
                name = _get_node_text(name_node, source_bytes) if name_node else None
                if name:
                    symbols.append(
                        ExtractedSymbol(
                            name=name,
                            symbol_type="module",
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=_get_first_line(_get_node_text(node, source_bytes)),
                            parent_symbol_name=parent_name,
                        )
                    )
                    for child in node.children:
                        _traverse(child, parent_name=name)
                    return

            if node.type == "struct_definition":
                type_head = next(
                    (c for c in node.children if c.type in ("type_head", "identifier")), None
                )
                name_node = (
                    next((c for c in type_head.children if c.type == "identifier"), type_head)
                    if type_head
                    else None
                )
                name = _get_node_text(name_node, source_bytes) if name_node else None
                if name:
                    symbols.append(
                        ExtractedSymbol(
                            name=name,
                            symbol_type="struct",
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=_get_first_line(_get_node_text(node, source_bytes)),
                            parent_symbol_name=parent_name,
                        )
                    )
                    return

            if node.type in ("function_definition", "macro_definition"):
                sig_node = next((c for c in node.children if c.type == "signature"), None)
                name = None
                if sig_node:
                    call_exp = next(
                        (c for c in sig_node.children if c.type == "call_expression"), None
                    )
                    if not call_exp:
                        typed_exp = next(
                            (c for c in sig_node.children if c.type == "typed_expression"), None
                        )
                        if typed_exp:
                            call_exp = next(
                                (c for c in typed_exp.children if c.type == "call_expression"),
                                None,
                            )
                    if call_exp:
                        ident = next((c for c in call_exp.children if c.type == "identifier"), None)
                        name = _get_node_text(ident, source_bytes) if ident else None
                if not name:
                    raw = _get_node_text(node, source_bytes).strip()
                    tokens = raw.split()
                    if len(tokens) >= 2:
                        name = tokens[1].split("(")[0].strip()

                if name:
                    symbols.append(
                        ExtractedSymbol(
                            name=name,
                            symbol_type="function",
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=_get_first_line(_get_node_text(node, source_bytes)),
                            parent_symbol_name=parent_name,
                        )
                    )
                    return

            if node.type in ("using_statement", "import_statement"):
                raw = _get_node_text(node, source_bytes).strip()
                ident = next((c for c in node.children if c.type == "identifier"), None)
                mod = _get_node_text(ident, source_bytes) if ident else raw.split()[-1]
                imports.append(ExtractedImport(module_name=mod, raw_statement=raw))
                return

            for child in node.children:
                _traverse(child, parent_name=parent_name)

        _traverse(root)
        return _dedup_and_validate(symbols, imports)


# -----------------------------------------------------------------------------
# 21. Zig Dedicated Adapter
# -----------------------------------------------------------------------------


class ZigAdapter(BaseLanguageAdapter):
    def extract(
        self, root: Node, source_bytes: bytes
    ) -> tuple[list[ExtractedSymbol], list[ExtractedImport]]:
        symbols: list[ExtractedSymbol] = []
        imports: list[ExtractedImport] = []

        def _traverse(node: Node, parent_name: str | None = None) -> None:
            if node.type in ("function_declaration", "fn_proto"):
                name_node = next((c for c in node.children if c.type == "identifier"), None)
                name = _get_node_text(name_node, source_bytes) if name_node else None
                if name:
                    symbols.append(
                        ExtractedSymbol(
                            name=name,
                            symbol_type="function",
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=_get_first_line(_get_node_text(node, source_bytes)),
                            parent_symbol_name=parent_name,
                        )
                    )
                    return

            if node.type == "variable_declaration":
                raw = _get_node_text(node, source_bytes).strip()
                if "struct" in raw or "enum" in raw or "union" in raw:
                    stype = "enum" if "enum" in raw else "struct"
                    ident = next((c for c in node.children if c.type == "identifier"), None)
                    name = _get_node_text(ident, source_bytes) if ident else None
                    if name:
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
                if "@import" in raw:
                    import re

                    match = re.search(r"@import\s*\(\s*['\"]([^'\"]+)['\"]\s*\)", raw)
                    if match:
                        imports.append(
                            ExtractedImport(module_name=match.group(1), raw_statement=raw)
                        )

            if node.type == "test_declaration":
                raw = _get_node_text(node, source_bytes).strip()
                tokens = raw.split('"')
                test_name = tokens[1] if len(tokens) >= 2 else "test"
                symbols.append(
                    ExtractedSymbol(
                        name=test_name,
                        symbol_type="function",
                        start_line=node.start_point.row + 1,
                        end_line=node.end_point.row + 1,
                        start_column=node.start_point.column,
                        end_column=node.end_point.column,
                        signature=_get_first_line(raw),
                    )
                )
                return

            for child in node.children:
                _traverse(child, parent_name=parent_name)

        _traverse(root)
        return _dedup_and_validate(symbols, imports)


# -----------------------------------------------------------------------------
# 22. OCaml Dedicated Adapter
# -----------------------------------------------------------------------------


class OCamlAdapter(BaseLanguageAdapter):
    def extract(
        self, root: Node, source_bytes: bytes
    ) -> tuple[list[ExtractedSymbol], list[ExtractedImport]]:
        symbols: list[ExtractedSymbol] = []
        imports: list[ExtractedImport] = []

        def _traverse(node: Node, parent_name: str | None = None) -> None:
            if node.type in ("module_definition", "module_type_definition"):
                binding = next(
                    (c for c in node.children if c.type in ("module_binding", "module_name")), None
                )
                ident = (
                    next((c for c in binding.children if c.type == "module_name"), binding)
                    if binding
                    else None
                )
                name = _get_node_text(ident, source_bytes) if ident else None
                if name:
                    symbols.append(
                        ExtractedSymbol(
                            name=name,
                            symbol_type="module",
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=_get_first_line(_get_node_text(node, source_bytes)),
                            parent_symbol_name=parent_name,
                        )
                    )
                    for child in node.children:
                        _traverse(child, parent_name=name)
                    return

            if node.type == "type_definition":
                binding = next((c for c in node.children if c.type == "type_binding"), None)
                ident = (
                    next((c for c in binding.children if c.type == "type_constructor"), None)
                    if binding
                    else None
                )
                name = _get_node_text(ident, source_bytes) if ident else None
                if name:
                    symbols.append(
                        ExtractedSymbol(
                            name=name,
                            symbol_type="struct",
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=_get_first_line(_get_node_text(node, source_bytes)),
                            parent_symbol_name=parent_name,
                        )
                    )
                    return

            if node.type == "value_definition":
                binding = next((c for c in node.children if c.type == "let_binding"), None)
                ident = (
                    next((c for c in binding.children if c.type == "value_name"), None)
                    if binding
                    else None
                )
                name = _get_node_text(ident, source_bytes) if ident else None
                if name:
                    symbols.append(
                        ExtractedSymbol(
                            name=name,
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

            if node.type == "open_module":
                path = next((c for c in node.children if c.type == "module_path"), None)
                mod = _get_node_text(path, source_bytes) if path else "unknown"
                raw = _get_node_text(node, source_bytes)
                imports.append(ExtractedImport(module_name=mod, raw_statement=raw))
                return

            for child in node.children:
                _traverse(child, parent_name=parent_name)

        _traverse(root)
        return _dedup_and_validate(symbols, imports)


# -----------------------------------------------------------------------------
# 23. Perl Dedicated Adapter
# -----------------------------------------------------------------------------


class PerlAdapter(BaseLanguageAdapter):
    def extract(
        self, root: Node, source_bytes: bytes
    ) -> tuple[list[ExtractedSymbol], list[ExtractedImport]]:
        symbols: list[ExtractedSymbol] = []
        imports: list[ExtractedImport] = []

        def _traverse(node: Node, parent_name: str | None = None) -> None:
            if node.type == "package_statement":
                pkg_node = next(
                    (
                        c
                        for c in node.children
                        if c.type in ("package", "bareword")
                        and _get_node_text(c, source_bytes) != "package"
                    ),
                    None,
                )
                name = _get_node_text(pkg_node, source_bytes) if pkg_node else None
                if not name:
                    raw = (
                        _get_node_text(node, source_bytes)
                        .replace("package", "")
                        .replace(";", "")
                        .strip()
                    )
                    name = raw.split()[0] if raw else None
                if name:
                    symbols.append(
                        ExtractedSymbol(
                            name=name,
                            symbol_type="module",
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=_get_first_line(_get_node_text(node, source_bytes)),
                            parent_symbol_name=parent_name,
                        )
                    )
                    return

            if node.type == "subroutine_declaration_statement":
                name_node = next((c for c in node.children if c.type == "bareword"), None)
                name = _get_node_text(name_node, source_bytes) if name_node else None
                if name:
                    symbols.append(
                        ExtractedSymbol(
                            name=name,
                            symbol_type="function",
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=_get_first_line(_get_node_text(node, source_bytes)),
                            parent_symbol_name=parent_name,
                        )
                    )
                    return

            if node.type == "use_statement":
                raw = _get_node_text(node, source_bytes).strip()
                pkg_node = next((c for c in node.children if c.type == "package"), None)
                mod = (
                    _get_node_text(pkg_node, source_bytes)
                    if pkg_node
                    else raw.replace("use", "").rstrip(";").strip()
                )
                imports.append(ExtractedImport(module_name=mod, raw_statement=raw))
                return

            for child in node.children:
                _traverse(child, parent_name=parent_name)

        _traverse(root)
        return _dedup_and_validate(symbols, imports)


# -----------------------------------------------------------------------------
# 24. Fortran Dedicated Adapter
# -----------------------------------------------------------------------------


class FortranAdapter(BaseLanguageAdapter):
    def extract(
        self, root: Node, source_bytes: bytes
    ) -> tuple[list[ExtractedSymbol], list[ExtractedImport]]:
        symbols: list[ExtractedSymbol] = []
        imports: list[ExtractedImport] = []

        def _traverse(node: Node, parent_name: str | None = None) -> None:
            if node.type == "module":
                stmt = next((c for c in node.children if c.type == "module_statement"), None)
                name_node = (
                    next((c for c in stmt.children if c.type == "name"), None) if stmt else None
                )
                name = _get_node_text(name_node, source_bytes) if name_node else None
                if name:
                    symbols.append(
                        ExtractedSymbol(
                            name=name,
                            symbol_type="module",
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=_get_first_line(_get_node_text(node, source_bytes)),
                            parent_symbol_name=parent_name,
                        )
                    )
                    for child in node.children:
                        _traverse(child, parent_name=name)
                    return

            if node.type in ("subroutine", "function"):
                stmt = next((c for c in node.children if "statement" in c.type), None)
                name_node = (
                    next((c for c in stmt.children if c.type == "name"), None) if stmt else None
                )
                if not name_node:
                    raw = _get_node_text(node, source_bytes)
                    tokens = raw.split()
                    for idx, t in enumerate(tokens):
                        if t.upper() in ("SUBROUTINE", "FUNCTION") and idx + 1 < len(tokens):
                            name = tokens[idx + 1].split("(")[0].strip()
                            break
                else:
                    name = _get_node_text(name_node, source_bytes)

                if name:
                    symbols.append(
                        ExtractedSymbol(
                            name=name,
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

            if node.type == "use_statement":
                raw = _get_node_text(node, source_bytes).strip()
                tokens = raw.split()
                mod = tokens[1].strip() if len(tokens) >= 2 else raw
                imports.append(ExtractedImport(module_name=mod, raw_statement=raw))
                return

            for child in node.children:
                _traverse(child, parent_name=parent_name)

        _traverse(root)
        return _dedup_and_validate(symbols, imports)


# -----------------------------------------------------------------------------
# 25. Pascal Dedicated Adapter
# -----------------------------------------------------------------------------


class PascalAdapter(BaseLanguageAdapter):
    def extract(
        self, root: Node, source_bytes: bytes
    ) -> tuple[list[ExtractedSymbol], list[ExtractedImport]]:
        symbols: list[ExtractedSymbol] = []
        imports: list[ExtractedImport] = []

        def _traverse(node: Node, parent_name: str | None = None) -> None:
            if node.type in ("unit", "program"):
                name_node = next(
                    (c for c in node.children if c.type in ("moduleName", "identifier")), None
                )
                name = _get_node_text(name_node, source_bytes) if name_node else None
                if name:
                    symbols.append(
                        ExtractedSymbol(
                            name=name,
                            symbol_type="module",
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=_get_first_line(_get_node_text(node, source_bytes)),
                            parent_symbol_name=parent_name,
                        )
                    )

            if node.type == "declProc":
                name_node = next((c for c in node.children if c.type == "identifier"), None)
                name = _get_node_text(name_node, source_bytes) if name_node else None
                if name:
                    symbols.append(
                        ExtractedSymbol(
                            name=name,
                            symbol_type="function",
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=_get_first_line(_get_node_text(node, source_bytes)),
                            parent_symbol_name=parent_name,
                        )
                    )
                    return

            if node.type == "declType":
                raw = _get_node_text(node, source_bytes).strip()
                tokens = raw.split("=")
                name = tokens[0].strip() if len(tokens) >= 2 else None
                if name:
                    stype = "interface" if "interface" in raw.lower() else "struct"
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
                    return

            if node.type == "uses":
                raw = _get_node_text(node, source_bytes).strip()
                mods = raw.replace("uses", "").rstrip(";").split(",")
                for m in mods:
                    cleaned = m.strip()
                    if cleaned:
                        imports.append(ExtractedImport(module_name=cleaned, raw_statement=raw))
                return

            for child in node.children:
                _traverse(child, parent_name=parent_name)

        _traverse(root)
        return _dedup_and_validate(symbols, imports)


# -----------------------------------------------------------------------------
# 26. CMake Dedicated Adapter
# -----------------------------------------------------------------------------


class CMakeAdapter(BaseLanguageAdapter):
    def extract(
        self, root: Node, source_bytes: bytes
    ) -> tuple[list[ExtractedSymbol], list[ExtractedImport]]:
        symbols: list[ExtractedSymbol] = []
        imports: list[ExtractedImport] = []

        def _traverse(node: Node) -> None:
            if node.type in ("function_def", "macro_def"):
                cmd = next((c for c in node.children if "command" in c.type), None)
                args = (
                    next((c for c in cmd.children if c.type == "argument_list"), None)
                    if cmd
                    else None
                )
                name_node = (
                    next((c for c in args.children if c.type == "argument"), None) if args else None
                )
                name = _get_node_text(name_node, source_bytes) if name_node else None
                if name:
                    symbols.append(
                        ExtractedSymbol(
                            name=name,
                            symbol_type="function",
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=_get_first_line(_get_node_text(node, source_bytes)),
                        )
                    )
                    return

            if node.type == "normal_command":
                ident = next((c for c in node.children if c.type == "identifier"), None)
                cmd_name = _get_node_text(ident, source_bytes).lower() if ident else ""
                args = next((c for c in node.children if c.type == "argument_list"), None)

                if cmd_name in ("add_library", "add_executable"):
                    target_arg = (
                        next((c for c in args.children if c.type == "argument"), None)
                        if args
                        else None
                    )
                    target_name = _get_node_text(target_arg, source_bytes) if target_arg else None
                    if target_name:
                        symbols.append(
                            ExtractedSymbol(
                                name=target_name,
                                symbol_type="struct",
                                start_line=node.start_point.row + 1,
                                end_line=node.end_point.row + 1,
                                start_column=node.start_point.column,
                                end_column=node.end_point.column,
                                signature=_get_first_line(_get_node_text(node, source_bytes)),
                            )
                        )

                elif cmd_name in ("find_package", "include"):
                    pkg_arg = (
                        next((c for c in args.children if c.type == "argument"), None)
                        if args
                        else None
                    )
                    pkg_name = _get_node_text(pkg_arg, source_bytes) if pkg_arg else None
                    if pkg_name:
                        imports.append(
                            ExtractedImport(
                                module_name=pkg_name,
                                raw_statement=_get_node_text(node, source_bytes).strip(),
                            )
                        )

            for child in node.children:
                _traverse(child)

        _traverse(root)
        return _dedup_and_validate(symbols, imports)


# -----------------------------------------------------------------------------
# 27. Make Dedicated Adapter
# -----------------------------------------------------------------------------


class MakeAdapter(BaseLanguageAdapter):
    def extract(
        self, root: Node, source_bytes: bytes
    ) -> tuple[list[ExtractedSymbol], list[ExtractedImport]]:
        symbols: list[ExtractedSymbol] = []
        imports: list[ExtractedImport] = []

        def _traverse(node: Node) -> None:
            if node.type == "rule":
                targets = next((c for c in node.children if c.type == "targets"), None)
                target_word = (
                    next((c for c in targets.children if c.type == "word"), None)
                    if targets
                    else None
                )
                name = _get_node_text(target_word, source_bytes) if target_word else None
                if name:
                    symbols.append(
                        ExtractedSymbol(
                            name=name,
                            symbol_type="function",
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=_get_first_line(_get_node_text(node, source_bytes)),
                        )
                    )
                    return

            if node.type == "include_directive":
                raw = _get_node_text(node, source_bytes).strip()
                tokens = raw.split()
                mod = tokens[1] if len(tokens) >= 2 else raw
                imports.append(ExtractedImport(module_name=mod, raw_statement=raw))
                return

            for child in node.children:
                _traverse(child)

        _traverse(root)
        return _dedup_and_validate(symbols, imports)


# -----------------------------------------------------------------------------
# 28. Structured Data & Markup Adapter (HTML, CSS, XML, Markdown, TOML, YAML, JSON)
# -----------------------------------------------------------------------------


class StructuredDataAndMarkupAdapter(BaseLanguageAdapter):
    """Handles structured documents, styling, and markup grammars."""

    def extract(
        self, root: Node, source_bytes: bytes
    ) -> tuple[list[ExtractedSymbol], list[ExtractedImport]]:
        symbols: list[ExtractedSymbol] = []
        imports: list[ExtractedImport] = []

        def _traverse(node: Node) -> None:
            raw = _get_node_text(node, source_bytes).strip()

            # CSS rule_set, keyframes, @import
            if node.type == "rule_set":
                selectors = next((c for c in node.children if c.type == "selectors"), None)
                sel_text = (
                    _get_node_text(selectors, source_bytes).strip()
                    if selectors
                    else raw.split("{")[0].strip()
                )
                if sel_text:
                    symbols.append(
                        ExtractedSymbol(
                            name=sel_text,
                            symbol_type="struct",
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=_get_first_line(raw),
                        )
                    )
                return

            if node.type == "keyframes_statement":
                name_node = next((c for c in node.children if c.type == "keyframes_name"), None)
                name = _get_node_text(name_node, source_bytes) if name_node else None
                if name:
                    symbols.append(
                        ExtractedSymbol(
                            name=name,
                            symbol_type="function",
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=_get_first_line(raw),
                        )
                    )
                return

            if node.type == "import_statement" and "@import" in raw:
                import re

                match = re.search(r"url\s*\(\s*['\"]([^'\"]+)['\"]\s*\)", raw) or re.search(
                    r"@import\s*['\"]([^'\"]+)['\"]", raw
                )
                mod = match.group(1) if match else raw.replace("@import", "").rstrip(";").strip()
                imports.append(ExtractedImport(module_name=mod, raw_statement=raw))
                return

            # Markdown Headings
            if node.type == "atx_heading":
                heading_text = raw.lstrip("#").strip()
                if heading_text:
                    symbols.append(
                        ExtractedSymbol(
                            name=heading_text,
                            symbol_type="struct",
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=_get_first_line(raw),
                        )
                    )
                return

            # TOML Tables
            if node.type == "table":
                key_node = next((c for c in node.children if c.type in ("bare_key", "key")), None)
                table_name = (
                    _get_node_text(key_node, source_bytes)
                    if key_node
                    else raw.split("]")[0].lstrip("[")
                )
                if table_name:
                    symbols.append(
                        ExtractedSymbol(
                            name=table_name,
                            symbol_type="struct",
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=_get_first_line(raw),
                        )
                    )
                return

            # HTML / XML elements & imports
            if node.type in ("element", "script_element"):
                if "<link " in raw and "stylesheet" in raw:
                    import re

                    match = re.search(r'href=["\']([^"\']+)["\']', raw)
                    if match:
                        imports.append(
                            ExtractedImport(
                                module_name=match.group(1), raw_statement=_get_first_line(raw)
                            )
                        )
                elif "<script " in raw and "src=" in raw:
                    import re

                    match = re.search(r'src=["\']([^"\']+)["\']', raw)
                    if match:
                        imports.append(
                            ExtractedImport(
                                module_name=match.group(1), raw_statement=_get_first_line(raw)
                            )
                        )

                import re

                id_match = re.search(r'id=["\']([^"\']+)["\']', raw)
                if id_match:
                    symbols.append(
                        ExtractedSymbol(
                            name=f"#{id_match.group(1)}",
                            symbol_type="struct",
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=_get_first_line(raw),
                        )
                    )

            # JSON root object keys & YAML root mappings
            if node.type in ("pair", "block_mapping_pair"):
                key_node = node.child_by_field_name("key")
                if not key_node:
                    key_node = next(
                        (c for c in node.children if c.type in ("string", "key", "flow_node")), None
                    )
                k_name = _get_node_text(key_node, source_bytes).strip("\"'") if key_node else None
                if (
                    k_name
                    and node.parent
                    and node.parent.type in ("object", "block_mapping", "document")
                ):
                    symbols.append(
                        ExtractedSymbol(
                            name=k_name,
                            symbol_type="struct",
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            start_column=node.start_point.column,
                            end_column=node.end_point.column,
                            signature=_get_first_line(raw),
                        )
                    )

            for child in node.children:
                _traverse(child)

        _traverse(root)
        return _dedup_and_validate(symbols, imports)


# -----------------------------------------------------------------------------
# 29. Generic Declarative Adapter (Fallback)
# -----------------------------------------------------------------------------


class GenericDeclarationAdapter(BaseLanguageAdapter):
    """
    General fallback adapter scanning function, class, table, and import nodes.
    Used for unrecognized languages or exotic constructs.
    """

    def extract(
        self, root: Node, source_bytes: bytes
    ) -> tuple[list[ExtractedSymbol], list[ExtractedImport]]:
        symbols: list[ExtractedSymbol] = []
        imports: list[ExtractedImport] = []

        def _traverse(node: Node, parent_name: str | None = None) -> None:
            if node.type in (
                "class_definition",
                "class_declaration",
                "contract_declaration",
                "defmodule",
                "struct_definition",
                "table_definition",
                "statement",
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

            elif node.type in (
                "function_declaration",
                "function_definition",
                "function_item",
                "method_definition",
            ):
                name_node = node.child_by_field_name("name")
                f_name = _get_node_text(name_node, source_bytes) if name_node else None
                raw = _get_node_text(node, source_bytes)
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

            for child in node.children:
                _traverse(child, parent_name=parent_name)

        _traverse(root)
        return _dedup_and_validate(symbols, imports)


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
    category: str = "general"
    extraction_mode: str = "validated"  # "validated" | "generic" | "fallback" | "detection_only"


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
                fn = getattr(mod, "language", None)
            if fn is None:
                # search for language_xml, language_php, language_ocaml, etc.
                for cand in dir(mod):
                    if cand.startswith("language_") and callable(getattr(mod, cand)):
                        fn = getattr(mod, cand)
                        break

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
        # Core Object-Oriented & Systems
        py = PythonAdapter()
        js = JavaScriptFamilyAdapter()
        java = JavaFamilyAdapter()
        c = CFamilyAdapter()
        cs = CSharpAdapter()
        php = PHPAdapter()
        go = GoAdapter()
        rust = RustAdapter()
        ruby = RubyAdapter()
        swift = SwiftAdapter()
        kt = KotlinAdapter()
        dart = DartAdapter()
        scala = ScalaAdapter()
        elixir = ElixirAdapter()
        hs = HaskellAdapter()
        sol = SolidityAdapter()
        lua = LuaAdapter()
        shell = ShellAdapter()
        sql = SQLAdapter()
        julia = JuliaAdapter()
        zig = ZigAdapter()
        ocaml = OCamlAdapter()
        perl = PerlAdapter()
        fortran = FortranAdapter()
        pascal = PascalAdapter()
        cmake = CMakeAdapter()
        make = MakeAdapter()
        markup = StructuredDataAndMarkupAdapter()

        # Core 7
        self.register_language(
            LanguageSpec(
                "Python",
                "tree_sitter_python",
                "language",
                py,
                [".py", ".pyw"],
                "general",
                "validated",
            )
        )
        self.register_language(
            LanguageSpec(
                "JavaScript",
                "tree_sitter_javascript",
                "language",
                js,
                [".js", ".mjs", ".cjs"],
                "web",
                "validated",
            )
        )
        self.register_language(
            LanguageSpec(
                "TypeScript",
                "tree_sitter_typescript",
                "language_typescript",
                js,
                [".ts", ".mts", ".cts"],
                "web",
                "validated",
            )
        )
        self.register_language(
            LanguageSpec(
                "TSX", "tree_sitter_typescript", "language_tsx", js, [".tsx"], "web", "validated"
            )
        )
        self.register_language(
            LanguageSpec(
                "JSX", "tree_sitter_typescript", "language_tsx", js, [".jsx"], "web", "validated"
            )
        )
        self.register_language(
            LanguageSpec(
                "Java", "tree_sitter_java", "language", java, [".java"], "backend", "validated"
            )
        )
        self.register_language(
            LanguageSpec("C", "tree_sitter_c", "language", c, [".c", ".h"], "systems", "validated")
        )
        self.register_language(
            LanguageSpec(
                "C++",
                "tree_sitter_cpp",
                "language",
                c,
                [".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx"],
                "systems",
                "validated",
            )
        )

        # Group A
        self.register_language(
            LanguageSpec(
                "PHP",
                "tree_sitter_php",
                "language_php",
                php,
                [".php", ".phtml"],
                "backend",
                "validated",
            )
        )
        self.register_language(
            LanguageSpec(
                "C#", "tree_sitter_c_sharp", "language", cs, [".cs"], "backend", "validated"
            )
        )
        self.register_language(
            LanguageSpec("Go", "tree_sitter_go", "language", go, [".go"], "backend", "validated")
        )
        self.register_language(
            LanguageSpec(
                "Rust", "tree_sitter_rust", "language", rust, [".rs"], "systems", "validated"
            )
        )
        self.register_language(
            LanguageSpec(
                "Ruby", "tree_sitter_ruby", "language", ruby, [".rb"], "backend", "validated"
            )
        )
        self.register_language(
            LanguageSpec(
                "Swift", "tree_sitter_swift", "language", swift, [".swift"], "mobile", "validated"
            )
        )
        self.register_language(
            LanguageSpec(
                "Kotlin",
                "tree_sitter_kotlin",
                "language",
                kt,
                [".kt", ".kts"],
                "mobile",
                "validated",
            )
        )
        self.register_language(
            LanguageSpec(
                "Dart", "tree_sitter_dart", "language", dart, [".dart"], "mobile", "validated"
            )
        )

        # Group B: Web and Database
        self.register_language(
            LanguageSpec(
                "HTML",
                "tree_sitter_html",
                "language",
                markup,
                [".html", ".htm"],
                "markup",
                "validated",
            )
        )
        self.register_language(
            LanguageSpec(
                "CSS",
                "tree_sitter_css",
                "language",
                markup,
                [".css", ".scss", ".sass"],
                "styling",
                "validated",
            )
        )
        self.register_language(
            LanguageSpec(
                "SQL", "tree_sitter_sql", "language", sql, [".sql"], "database", "validated"
            )
        )
        self.register_language(
            LanguageSpec(
                "Svelte", "tree_sitter_svelte", "language", markup, [".svelte"], "web", "generic"
            )
        )
        self.register_language(
            LanguageSpec(
                "YAML",
                "tree_sitter_yaml",
                "language",
                markup,
                [".yaml", ".yml"],
                "config",
                "validated",
            )
        )
        self.register_language(
            LanguageSpec(
                "XML", "tree_sitter_xml", "language_xml", markup, [".xml"], "markup", "validated"
            )
        )
        self.register_language(
            LanguageSpec(
                "JSON", "tree_sitter_json", "language", markup, [".json"], "data", "validated"
            )
        )
        self.register_language(
            LanguageSpec(
                "TOML", "tree_sitter_toml", "language", markup, [".toml"], "config", "validated"
            )
        )

        # Group C: Scripting and Functional
        self.register_language(
            LanguageSpec(
                "Bash",
                "tree_sitter_bash",
                "language",
                shell,
                [".sh", ".bash", ".zsh"],
                "scripting",
                "validated",
            )
        )
        self.register_language(
            LanguageSpec(
                "PowerShell",
                "tree_sitter_powershell",
                "language",
                shell,
                [".ps1", ".psm1", ".psd1"],
                "scripting",
                "validated",
            )
        )
        self.register_language(
            LanguageSpec(
                "Lua", "tree_sitter_lua", "language", lua, [".lua"], "scripting", "validated"
            )
        )
        self.register_language(
            LanguageSpec(
                "Scala",
                "tree_sitter_scala",
                "language",
                scala,
                [".scala", ".sc"],
                "functional",
                "validated",
            )
        )
        self.register_language(
            LanguageSpec(
                "Elixir",
                "tree_sitter_elixir",
                "language",
                elixir,
                [".ex", ".exs"],
                "functional",
                "validated",
            )
        )
        self.register_language(
            LanguageSpec(
                "Haskell",
                "tree_sitter_haskell",
                "language",
                hs,
                [".hs", ".lhs"],
                "functional",
                "validated",
            )
        )
        self.register_language(
            LanguageSpec(
                "Perl",
                "tree_sitter_perl",
                "language",
                perl,
                [".pl", ".pm"],
                "scripting",
                "validated",
            )
        )

        # Group D: Systems, Scientific and Build
        self.register_language(
            LanguageSpec(
                "Objective-C",
                "tree_sitter_objc",
                "language",
                c,
                [".m", ".mm"],
                "mobile",
                "validated",
            )
        )
        self.register_language(
            LanguageSpec(
                "OCaml",
                "tree_sitter_ocaml",
                "language_ocaml",
                ocaml,
                [".ml", ".mli"],
                "functional",
                "validated",
            )
        )
        self.register_language(
            LanguageSpec(
                "Julia", "tree_sitter_julia", "language", julia, [".jl"], "scientific", "validated"
            )
        )
        self.register_language(
            LanguageSpec(
                "Zig", "tree_sitter_zig", "language", zig, [".zig"], "systems", "validated"
            )
        )
        self.register_language(
            LanguageSpec(
                "Solidity",
                "tree_sitter_solidity",
                "language",
                sol,
                [".sol"],
                "smart-contracts",
                "validated",
            )
        )
        self.register_language(
            LanguageSpec(
                "Groovy",
                "tree_sitter_groovy",
                "language",
                java,
                [".groovy", ".gvy"],
                "backend",
                "validated",
            )
        )
        self.register_language(
            LanguageSpec(
                "Fortran",
                "tree_sitter_fortran",
                "language",
                fortran,
                [".f90", ".f95", ".f03", ".for", ".f"],
                "scientific",
                "validated",
            )
        )
        self.register_language(
            LanguageSpec(
                "Pascal",
                "tree_sitter_pascal",
                "language",
                pascal,
                [".pas", ".pp"],
                "systems",
                "validated",
            )
        )
        self.register_language(
            LanguageSpec(
                "CMake", "tree_sitter_cmake", "language", cmake, [".cmake"], "build", "validated"
            )
        )
        self.register_language(
            LanguageSpec(
                "Make",
                "tree_sitter_make",
                "language",
                make,
                ["makefile", "gnumakefile"],
                "build",
                "validated",
            )
        )
        self.register_language(
            LanguageSpec(
                "Markdown",
                "tree_sitter_markdown",
                "language",
                markup,
                [".md", ".markdown"],
                "documentation",
                "validated",
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
