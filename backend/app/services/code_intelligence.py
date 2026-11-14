import logging
from dataclasses import dataclass, field

from tree_sitter import Language, Node, Parser

logger = logging.getLogger("orchestrix.intelligence")

# -----------------------------------------------------------------------------
# Parser Cache (Lazily initialized once for performance)
# -----------------------------------------------------------------------------

_PARSER_CACHE: dict[str, Parser] = {}


def _get_parser(language_name: str) -> Parser | None:
    """Retrieve or initialize a Tree-sitter Parser for supported languages."""
    if language_name in _PARSER_CACHE:
        return _PARSER_CACHE[language_name]

    try:
        if language_name == "Python":
            import tree_sitter_python

            lang = Language(tree_sitter_python.language())
        elif language_name == "JavaScript":
            import tree_sitter_javascript

            lang = Language(tree_sitter_javascript.language())
        elif language_name == "TypeScript":
            import tree_sitter_typescript

            lang = Language(tree_sitter_typescript.language_typescript())
        elif language_name == "TSX" or language_name == "JSX":
            import tree_sitter_typescript

            lang = Language(tree_sitter_typescript.language_tsx())
        elif language_name == "Java":
            import tree_sitter_java

            lang = Language(tree_sitter_java.language())
        elif language_name == "C":
            import tree_sitter_c

            lang = Language(tree_sitter_c.language())
        elif language_name == "C++":
            import tree_sitter_cpp

            lang = Language(tree_sitter_cpp.language())
        else:
            return None

        parser = Parser(lang)
        _PARSER_CACHE[language_name] = parser
        return parser
    except Exception as exc:
        logger.warning("Failed to initialize tree-sitter parser for %s: %s", language_name, exc)
        return None


# -----------------------------------------------------------------------------
# Symbol & Import Dataclasses
# -----------------------------------------------------------------------------


@dataclass
class ExtractedSymbol:
    name: str
    symbol_type: str  # "function", "class", "method", "interface"
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
# Language-Specific AST Extractors
# -----------------------------------------------------------------------------


def _get_node_text(node: Node, source_bytes: bytes) -> str:
    """Extract decoded text of a node safely."""
    return source_bytes[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _get_first_line(text: str) -> str:
    """Extract first non-empty line of code for signatures."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return lines[0] if lines else ""


def _extract_python_symbols(
    root: Node, source_bytes: bytes
) -> tuple[list[ExtractedSymbol], list[ExtractedImport]]:
    symbols: list[ExtractedSymbol] = []
    imports: list[ExtractedImport] = []

    def _traverse(node: Node, parent_class: str | None = None) -> None:
        if node.type == "function_definition":
            name_node = node.child_by_field_name("name")
            if name_node:
                name = _get_node_text(name_node, source_bytes)
                sig = _get_first_line(_get_node_text(node, source_bytes))
                sym_type = "method" if parent_class else "function"
                symbols.append(
                    ExtractedSymbol(
                        name=name,
                        symbol_type=sym_type,
                        start_line=node.start_point.row + 1,
                        end_line=node.end_point.row + 1,
                        start_column=node.start_point.column,
                        end_column=node.end_point.column,
                        signature=sig,
                        parent_symbol_name=parent_class,
                    )
                )
            return

        if node.type == "class_definition":
            name_node = node.child_by_field_name("name")
            class_name = _get_node_text(name_node, source_bytes) if name_node else "UnknownClass"
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

        if node.type == "import_statement":
            # e.g., import os, sys
            text = _get_node_text(node, source_bytes)
            for child in node.children:
                if child.type == "dotted_name":
                    mod_name = _get_node_text(child, source_bytes)
                    imports.append(
                        ExtractedImport(
                            module_name=mod_name,
                            is_external=not mod_name.startswith("."),
                            raw_statement=text,
                        )
                    )
            return

        if node.type == "import_from_statement":
            # e.g., from app.services import auth
            mod_node = node.child_by_field_name("module_name")
            text = _get_node_text(node, source_bytes)
            if mod_node:
                mod_name = _get_node_text(mod_node, source_bytes)
                imports.append(
                    ExtractedImport(
                        module_name=mod_name,
                        is_external=not mod_name.startswith("."),
                        raw_statement=text,
                    )
                )
            return

        for child in node.children:
            _traverse(child, parent_class=parent_class)

    _traverse(root)
    return symbols, imports


def _extract_js_ts_symbols(
    root: Node, source_bytes: bytes
) -> tuple[list[ExtractedSymbol], list[ExtractedImport]]:
    symbols: list[ExtractedSymbol] = []
    imports: list[ExtractedImport] = []

    def _traverse(node: Node, parent_class: str | None = None) -> None:
        target_node = node
        # Unwrap export statements
        if node.type == "export_statement":
            decl = node.child_by_field_name("declaration")
            if decl:
                target_node = decl

        if target_node.type in ("function_declaration", "function"):
            name_node = target_node.child_by_field_name("name")
            if name_node:
                name = _get_node_text(name_node, source_bytes)
                sig = _get_first_line(_get_node_text(target_node, source_bytes))
                sym_type = "method" if parent_class else "function"
                symbols.append(
                    ExtractedSymbol(
                        name=name,
                        symbol_type=sym_type,
                        start_line=target_node.start_point.row + 1,
                        end_line=target_node.end_point.row + 1,
                        start_column=target_node.start_point.column,
                        end_column=target_node.end_point.column,
                        signature=sig,
                        parent_symbol_name=parent_class,
                    )
                )
            return

        if target_node.type == "method_definition":
            name_node = target_node.child_by_field_name("name")
            if name_node:
                name = _get_node_text(name_node, source_bytes)
                sig = _get_first_line(_get_node_text(target_node, source_bytes))
                symbols.append(
                    ExtractedSymbol(
                        name=name,
                        symbol_type="method",
                        start_line=target_node.start_point.row + 1,
                        end_line=target_node.end_point.row + 1,
                        start_column=target_node.start_point.column,
                        end_column=target_node.end_point.column,
                        signature=sig,
                        parent_symbol_name=parent_class,
                    )
                )
            return

        if target_node.type in ("class_declaration", "class"):
            name_node = target_node.child_by_field_name("name")
            class_name = _get_node_text(name_node, source_bytes) if name_node else "AnonymousClass"
            sig = _get_first_line(_get_node_text(target_node, source_bytes))
            symbols.append(
                ExtractedSymbol(
                    name=class_name,
                    symbol_type="class",
                    start_line=target_node.start_point.row + 1,
                    end_line=target_node.end_point.row + 1,
                    start_column=target_node.start_point.column,
                    end_column=target_node.end_point.column,
                    signature=sig,
                    parent_symbol_name=parent_class,
                )
            )
            body = target_node.child_by_field_name("body")
            if body:
                for child in body.children:
                    _traverse(child, parent_class=class_name)
            return

        if target_node.type == "interface_declaration":
            name_node = target_node.child_by_field_name("name")
            if name_node:
                name = _get_node_text(name_node, source_bytes)
                sig = _get_first_line(_get_node_text(target_node, source_bytes))
                symbols.append(
                    ExtractedSymbol(
                        name=name,
                        symbol_type="interface",
                        start_line=target_node.start_point.row + 1,
                        end_line=target_node.end_point.row + 1,
                        start_column=target_node.start_point.column,
                        end_column=target_node.end_point.column,
                        signature=sig,
                        parent_symbol_name=parent_class,
                    )
                )
            return

        if node.type == "import_statement":
            src_node = node.child_by_field_name("source")
            if src_node:
                raw_mod = _get_node_text(src_node, source_bytes).strip("\"'")
                is_ext = not (raw_mod.startswith(".") or raw_mod.startswith("/"))
                imports.append(
                    ExtractedImport(
                        module_name=raw_mod,
                        is_external=is_ext,
                        raw_statement=_get_node_text(node, source_bytes),
                    )
                )
            return

        for child in node.children:
            _traverse(child, parent_class=parent_class)

    _traverse(root)
    return symbols, imports


def _extract_java_symbols(
    root: Node, source_bytes: bytes
) -> tuple[list[ExtractedSymbol], list[ExtractedImport]]:
    symbols: list[ExtractedSymbol] = []
    imports: list[ExtractedImport] = []

    def _traverse(node: Node, parent_class: str | None = None) -> None:
        if node.type == "class_declaration":
            name_node = node.child_by_field_name("name")
            class_name = _get_node_text(name_node, source_bytes) if name_node else "JavaClass"
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

        if node.type == "interface_declaration":
            name_node = node.child_by_field_name("name")
            if name_node:
                name = _get_node_text(name_node, source_bytes)
                symbols.append(
                    ExtractedSymbol(
                        name=name,
                        symbol_type="interface",
                        start_line=node.start_point.row + 1,
                        end_line=node.end_point.row + 1,
                        start_column=node.start_point.column,
                        end_column=node.end_point.column,
                        signature=_get_first_line(_get_node_text(node, source_bytes)),
                        parent_symbol_name=parent_class,
                    )
                )
            return

        if node.type in ("method_declaration", "constructor_declaration"):
            name_node = node.child_by_field_name("name")
            if name_node:
                name = _get_node_text(name_node, source_bytes)
                sig = _get_first_line(_get_node_text(node, source_bytes))
                symbols.append(
                    ExtractedSymbol(
                        name=name,
                        symbol_type="method" if parent_class else "function",
                        start_line=node.start_point.row + 1,
                        end_line=node.end_point.row + 1,
                        start_column=node.start_point.column,
                        end_column=node.end_point.column,
                        signature=sig,
                        parent_symbol_name=parent_class,
                    )
                )
            return

        if node.type == "import_declaration":
            # e.g., import java.util.List;
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
                        module_name=text,
                        is_external=True,
                        raw_statement=_get_node_text(node, source_bytes),
                    )
                )
            return

        for child in node.children:
            _traverse(child, parent_class=parent_class)

    _traverse(root)
    return symbols, imports


def _extract_c_cpp_symbols(
    root: Node, source_bytes: bytes
) -> tuple[list[ExtractedSymbol], list[ExtractedImport]]:
    symbols: list[ExtractedSymbol] = []
    imports: list[ExtractedImport] = []

    def _find_declarator_identifier(dec_node: Node) -> str | None:
        if dec_node.type in ("identifier", "field_identifier"):
            return _get_node_text(dec_node, source_bytes)
        for child in dec_node.children:
            found = _find_declarator_identifier(child)
            if found:
                return found
        return None

    def _traverse(node: Node, parent_class: str | None = None) -> None:
        if node.type in ("class_specifier", "struct_specifier"):
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

        if node.type == "function_definition":
            dec = node.child_by_field_name("declarator")
            if dec:
                func_name = _find_declarator_identifier(dec)
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
            return

        if node.type == "preproc_include":
            # e.g., #include <stdio.h> or #include "header.h"
            path_node = node.child_by_field_name("path")
            if path_node:
                raw_path = _get_node_text(path_node, source_bytes).strip("<>\"'")
                is_ext = _get_node_text(path_node, source_bytes).startswith("<")
                imports.append(
                    ExtractedImport(
                        module_name=raw_path,
                        is_external=is_ext,
                        raw_statement=_get_node_text(node, source_bytes),
                    )
                )
            return

        for child in node.children:
            _traverse(child, parent_class=parent_class)

    _traverse(root)
    return symbols, imports


# -----------------------------------------------------------------------------
# Main Public Interface
# -----------------------------------------------------------------------------


def analyze_code_content(
    content_bytes: bytes,
    language: str,
) -> FileIntelligence:
    """
    Parse source code with Tree-sitter and extract symbols and imports.
    Gracefully handles parsing failures and unsupported languages.
    """
    line_count = len(content_bytes.splitlines()) if content_bytes else 0
    parser = _get_parser(language)

    if not parser:
        return FileIntelligence(
            language=language,
            line_count=line_count,
            symbols=[],
            imports=[],
            parse_error=f"No Tree-sitter parser available for language '{language}'",
        )

    try:
        tree = parser.parse(content_bytes)
        root = tree.root_node

        if language == "Python":
            symbols, imports = _extract_python_symbols(root, content_bytes)
        elif language in ("JavaScript", "TypeScript", "TSX", "JSX"):
            symbols, imports = _extract_js_ts_symbols(root, content_bytes)
        elif language == "Java":
            symbols, imports = _extract_java_symbols(root, content_bytes)
        elif language in ("C", "C++"):
            symbols, imports = _extract_c_cpp_symbols(root, content_bytes)
        else:
            symbols, imports = [], []

        return FileIntelligence(
            language=language,
            line_count=line_count,
            symbols=symbols,
            imports=imports,
            parse_error=None,
        )
    except Exception as exc:
        logger.error("Tree-sitter analysis error on %s: %s", language, exc, exc_info=True)
        return FileIntelligence(
            language=language,
            line_count=line_count,
            symbols=[],
            imports=[],
            parse_error=f"Tree-sitter parsing exception: {exc}",
        )
