import logging
import uuid
from dataclasses import dataclass, field

from app.services.semantic_retrieval import RetrievedChunkResult

logger = logging.getLogger("orchestrix.context_assembly")

DEFAULT_MAX_CONTEXT_CHARS = 32000  # ~8000 tokens


@dataclass
class AssembledCodeBlock:
    """Consolidated code block from one file."""

    file_path: str
    language: str
    start_line: int
    end_line: int
    symbol_name: str | None
    symbol_type: str | None
    parent_symbol_name: str | None
    code: str
    similarity_score: float


@dataclass
class AssembledContext:
    """Structured context ready for LLM agent prompt injection."""

    repository_id: uuid.UUID
    repository_name: str
    query: str
    total_chunks_retrieved: int
    total_blocks_included: int
    total_characters: int
    estimated_tokens: int
    formatted_context_markdown: str
    blocks: list[AssembledCodeBlock] = field(default_factory=list)


class ContextAssemblyEngine:
    """
    Consolidates retrieved code chunks into cohesive, bounded, deduplicated context
    tailored for agent consumption (DevPilot, ImpactMind).
    """

    def __init__(self, max_context_chars: int = DEFAULT_MAX_CONTEXT_CHARS) -> None:
        self.max_context_chars = max_context_chars

    def assemble(
        self,
        repository_id: uuid.UUID,
        repository_name: str,
        query: str,
        retrieved_chunks: list[RetrievedChunkResult],
        max_chars: int | None = None,
    ) -> AssembledContext:
        """
        Assemble chunks into ordered Markdown blocks within token/char bounds.
        """
        budget = max_chars or self.max_context_chars
        if not retrieved_chunks:
            return AssembledContext(
                repository_id=repository_id,
                repository_name=repository_name,
                query=query,
                total_chunks_retrieved=0,
                total_blocks_included=0,
                total_characters=0,
                estimated_tokens=0,
                formatted_context_markdown="No relevant code context found for query.",
            )

        # 1. Deduplicate chunks covering the exact same lines in a file
        seen_ranges: set[tuple[str, int, int]] = set()
        unique_chunks: list[RetrievedChunkResult] = []
        for chk in retrieved_chunks:
            key = (chk.file_path, chk.start_line, chk.end_line)
            if key in seen_ranges:
                continue
            seen_ranges.add(key)
            unique_chunks.append(chk)

        # 2. Build blocks while respecting character budget
        blocks: list[AssembledCodeBlock] = []
        current_chars = 0
        md_sections: list[str] = [
            f"# Repository Context: {repository_name}",
            f"**Query**: `{query}`\n",
            "The following source code excerpts were semantically retrieved from the indexed repository:\n",
        ]

        for chunk in unique_chunks:
            header_lines = [
                f"### File: `{chunk.file_path}` (Lines {chunk.start_line}-{chunk.end_line})",
                f"- **Language**: {chunk.language}",
            ]
            if chunk.symbol_name:
                header_lines.append(
                    f"- **Symbol**: `{chunk.symbol_name}` ({chunk.symbol_type or 'code'})"
                )
            if chunk.parent_symbol_name:
                header_lines.append(f"- **Parent**: `{chunk.parent_symbol_name}`")
            header_lines.append(f"- **Relevance**: {int(chunk.similarity_score * 100)}%")

            meta = chunk.metadata or {}
            sig = meta.get("signature")
            if sig:
                header_lines.append(f"- **Signature**: `{sig}`")

            header_str = "\n".join(header_lines)
            lang_fence = chunk.language.lower() if chunk.language else ""
            block_md = f"{header_str}\n```{lang_fence}\n{chunk.content}\n```\n"

            block_len = len(block_md)
            if current_chars + block_len > budget and blocks:
                # Budget reached
                logger.info(
                    "Context budget reached (%d / %d chars). Capping at %d blocks.",
                    current_chars,
                    budget,
                    len(blocks),
                )
                break

            md_sections.append(block_md)
            current_chars += block_len
            blocks.append(
                AssembledCodeBlock(
                    file_path=chunk.file_path,
                    language=chunk.language,
                    start_line=chunk.start_line,
                    end_line=chunk.end_line,
                    symbol_name=chunk.symbol_name,
                    symbol_type=chunk.symbol_type,
                    parent_symbol_name=chunk.parent_symbol_name,
                    code=chunk.content,
                    similarity_score=chunk.similarity_score,
                )
            )

        full_md = "\n".join(md_sections)
        estimated_tokens = max(1, len(full_md) // 4)

        return AssembledContext(
            repository_id=repository_id,
            repository_name=repository_name,
            query=query,
            total_chunks_retrieved=len(retrieved_chunks),
            total_blocks_included=len(blocks),
            total_characters=len(full_md),
            estimated_tokens=estimated_tokens,
            formatted_context_markdown=full_md,
            blocks=blocks,
        )
