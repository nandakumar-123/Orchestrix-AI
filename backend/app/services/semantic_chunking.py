import hashlib
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from app.services.code_intelligence import ExtractedImport, ExtractedSymbol

logger = logging.getLogger("orchestrix.semantic_chunking")

# Sensitive token / secret redaction patterns
SECRET_PATTERNS = [
    re.compile(r"(?i)(bearer\s+ey[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,})"),
    re.compile(r"(?i)(api[_-]?key\s*[:=]\s*['\"])([a-zA-Z0-9_\-]{16,})(['\"])"),
    re.compile(r"(?i)(secret[_-]?key\s*[:=]\s*['\"])([a-zA-Z0-9_\-]{16,})(['\"])"),
    re.compile(r"(?i)(access[_-]?token\s*[:=]\s*['\"])([a-zA-Z0-9_\-]{16,})(['\"])"),
    re.compile(r"(ghp_[a-zA-Z0-9]{30,})"),
    re.compile(r"(glpat-[a-zA-Z0-9_\-]{20,})"),
    re.compile(r"(sk-[a-zA-Z0-9]{20,})"),
    re.compile(r"(AIza[0-9A-Za-z\-_]{35})"),
]


def redact_secrets(text: str) -> str:
    """Redact sensitive keys, tokens, or credentials before chunking and embedding."""
    redacted = text
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub(
            r"\1[REDACTED_SECRET]\3" if pattern.groups == 3 else "[REDACTED_SECRET]", redacted
        )
    return redacted


def compute_content_hash(text: str) -> str:
    """Generate deterministic SHA256 hex digest of text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class GeneratedChunk:
    """Structure-aware semantic chunk representation."""

    file_path: str
    language: str
    symbol_name: str | None
    symbol_type: str | None
    parent_symbol_name: str | None
    start_line: int
    end_line: int
    chunk_index: int
    content: str
    content_hash: str
    embeddable_text: (
        str  # Contextualized text with header and imports optimized for semantic retrieval
    )
    metadata: dict[str, Any] = field(default_factory=dict)


class ASTSemanticChunker:
    """
    Structure-aware code chunking engine utilizing Tree-sitter AST extraction.
    Creates semantically coherent chunks bounded by AST symbol definitions,
    with hierarchical context enrichment and sensitive data redaction.
    """

    def __init__(
        self,
        max_chunk_lines: int = 100,
        min_chunk_lines: int = 3,
        overlap_lines: int = 15,
    ) -> None:
        self.max_chunk_lines = max_chunk_lines
        self.min_chunk_lines = min_chunk_lines
        self.overlap_lines = overlap_lines

    def chunk_file(
        self,
        file_path: str,
        content_bytes: bytes,
        language: str,
        symbols: list[ExtractedSymbol],
        imports: list[ExtractedImport],
    ) -> list[GeneratedChunk]:
        """
        Generate semantic chunks from file source code and AST extractions.
        """
        text = content_bytes.decode("utf-8", errors="replace")
        text = redact_secrets(text)
        lines = text.splitlines()
        total_lines = len(lines)

        if total_lines == 0:
            return []

        chunks: list[GeneratedChunk] = []
        chunk_idx = 0

        # Build imports summary for context header
        import_names = [imp.module_name for imp in imports[:10]]
        imports_header = f"Imports: {', '.join(import_names)}" if import_names else ""

        # 1. File Overview / Top-level Context Chunk
        # Includes first 30-50 lines or top-level docstrings, imports, and structure
        overview_end = min(total_lines, 40)
        overview_content = "\n".join(lines[:overview_end])
        if overview_content.strip():
            embed_text = self._build_embeddable_text(
                file_path=file_path,
                language=language,
                symbol_name="File Overview",
                symbol_type="file_summary",
                parent_symbol_name=None,
                imports_header=imports_header,
                code_content=overview_content,
            )
            chunks.append(
                GeneratedChunk(
                    file_path=file_path,
                    language=language,
                    symbol_name="File Overview",
                    symbol_type="file_summary",
                    parent_symbol_name=None,
                    start_line=1,
                    end_line=overview_end,
                    chunk_index=chunk_idx,
                    content=overview_content,
                    content_hash=compute_content_hash(overview_content),
                    embeddable_text=embed_text,
                    metadata={"category": "file_overview", "total_file_lines": total_lines},
                )
            )
            chunk_idx += 1

        # 2. Symbol-aware Chunks
        # Group symbols by parent or top-level hierarchy
        symbols_sorted = sorted(symbols, key=lambda s: (s.start_line, -s.end_line))

        covered_ranges: set[tuple[int, int]] = set()

        for sym in symbols_sorted:
            s_line = max(1, sym.start_line)
            e_line = min(total_lines, sym.end_line)
            line_span = e_line - s_line + 1

            if line_span < self.min_chunk_lines:
                continue

            # Check if this exact range was already covered
            if (s_line, e_line) in covered_ranges:
                continue

            symbol_lines = lines[s_line - 1 : e_line]
            symbol_code = "\n".join(symbol_lines)

            # If class or struct is large, extract its header/outline, and let methods be chunks
            if (
                sym.symbol_type in ("class", "interface", "struct", "module")
                and line_span > self.max_chunk_lines
            ):
                # Class header outline (up to 40 lines)
                header_lines = lines[s_line - 1 : min(e_line, s_line + 35)]
                header_code = "\n".join(header_lines)
                embed_text = self._build_embeddable_text(
                    file_path=file_path,
                    language=language,
                    symbol_name=sym.name,
                    symbol_type=sym.symbol_type,
                    parent_symbol_name=sym.parent_symbol_name,
                    imports_header=imports_header,
                    code_content=header_code,
                )
                chunks.append(
                    GeneratedChunk(
                        file_path=file_path,
                        language=language,
                        symbol_name=sym.name,
                        symbol_type=sym.symbol_type,
                        parent_symbol_name=sym.parent_symbol_name,
                        start_line=s_line,
                        end_line=min(e_line, s_line + 35),
                        chunk_index=chunk_idx,
                        content=header_code,
                        content_hash=compute_content_hash(header_code),
                        embeddable_text=embed_text,
                        metadata={
                            "signature": sym.signature,
                            "is_class_outline": True,
                        },
                    )
                )
                chunk_idx += 1
                covered_ranges.add((s_line, e_line))
                continue

            # If a single function is extremely large (> max_chunk_lines), split into bounded sliding windows
            if line_span > self.max_chunk_lines:
                sub_start = s_line
                sub_part = 0
                while sub_start <= e_line:
                    sub_end = min(e_line, sub_start + self.max_chunk_lines - 1)
                    sub_code = "\n".join(lines[sub_start - 1 : sub_end])
                    part_name = f"{sym.name} (part {sub_part + 1})"
                    embed_text = self._build_embeddable_text(
                        file_path=file_path,
                        language=language,
                        symbol_name=part_name,
                        symbol_type=sym.symbol_type,
                        parent_symbol_name=sym.parent_symbol_name,
                        imports_header=imports_header,
                        code_content=sub_code,
                    )
                    chunks.append(
                        GeneratedChunk(
                            file_path=file_path,
                            language=language,
                            symbol_name=part_name,
                            symbol_type=sym.symbol_type,
                            parent_symbol_name=sym.parent_symbol_name,
                            start_line=sub_start,
                            end_line=sub_end,
                            chunk_index=chunk_idx,
                            content=sub_code,
                            content_hash=compute_content_hash(sub_code),
                            embeddable_text=embed_text,
                            metadata={
                                "signature": sym.signature,
                                "window_part": sub_part + 1,
                            },
                        )
                    )
                    chunk_idx += 1
                    sub_part += 1
                    if sub_end >= e_line:
                        break
                    sub_start = sub_end - self.overlap_lines + 1
                covered_ranges.add((s_line, e_line))
                continue

            # Standard symbol chunk
            embed_text = self._build_embeddable_text(
                file_path=file_path,
                language=language,
                symbol_name=sym.name,
                symbol_type=sym.symbol_type,
                parent_symbol_name=sym.parent_symbol_name,
                imports_header=imports_header,
                code_content=symbol_code,
            )
            chunks.append(
                GeneratedChunk(
                    file_path=file_path,
                    language=language,
                    symbol_name=sym.name,
                    symbol_type=sym.symbol_type,
                    parent_symbol_name=sym.parent_symbol_name,
                    start_line=s_line,
                    end_line=e_line,
                    chunk_index=chunk_idx,
                    content=symbol_code,
                    content_hash=compute_content_hash(symbol_code),
                    embeddable_text=embed_text,
                    metadata={"signature": sym.signature},
                )
            )
            chunk_idx += 1
            covered_ranges.add((s_line, e_line))

        # 3. Fallback for files without extracted AST symbols (e.g. scripts, configs, JSON, YAML)
        if len(chunks) <= 1 and total_lines > 40:
            cursor = 41
            block_idx = 1
            while cursor <= total_lines:
                block_end = min(total_lines, cursor + self.max_chunk_lines - 1)
                block_code = "\n".join(lines[cursor - 1 : block_end])
                if block_code.strip():
                    sym_label = f"Block {block_idx}"
                    embed_text = self._build_embeddable_text(
                        file_path=file_path,
                        language=language,
                        symbol_name=sym_label,
                        symbol_type="config_block",
                        parent_symbol_name=None,
                        imports_header="",
                        code_content=block_code,
                    )
                    chunks.append(
                        GeneratedChunk(
                            file_path=file_path,
                            language=language,
                            symbol_name=sym_label,
                            symbol_type="config_block",
                            parent_symbol_name=None,
                            start_line=cursor,
                            end_line=block_end,
                            chunk_index=chunk_idx,
                            content=block_code,
                            content_hash=compute_content_hash(block_code),
                            embeddable_text=embed_text,
                            metadata={"block_part": block_idx},
                        )
                    )
                    chunk_idx += 1
                    block_idx += 1
                cursor = block_end + 1

        return chunks

    def _build_embeddable_text(
        self,
        file_path: str,
        language: str,
        symbol_name: str | None,
        symbol_type: str | None,
        parent_symbol_name: str | None,
        imports_header: str,
        code_content: str,
    ) -> str:
        """
        Create semantically rich representation combining structural metadata and code.
        """
        parts = [f"File: {file_path}", f"Language: {language}"]
        if symbol_name:
            parts.append(f"Symbol: {symbol_name} ({symbol_type or 'code'})")
        if parent_symbol_name:
            parts.append(f"Parent: {parent_symbol_name}")
        if imports_header:
            parts.append(imports_header)

        header = " | ".join(parts)
        return f"{header}\n\n{code_content}"
