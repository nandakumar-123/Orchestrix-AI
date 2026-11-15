from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.repository_intelligence import CodeSymbol, RepositoryFile, RepositorySnapshot
from app.services.context_assembly import ContextAssemblyEngine
from app.services.graph_query_engine import GraphQueryEngine
from app.services.graph_service import BaseGraphProvider, get_graph_provider
from app.services.semantic_retrieval import SemanticRetrievalEngine

logger = logging.getLogger("orchestrix.devpilot.context_builder")

MAX_DEV_PILOT_CONTEXT_CHARS = 32000  # ~8000 tokens maximum budget
AMBIGUOUS_PROMPTS = {"fix", "update", "change", "refactor", "do it", "help", "build"}
DANGEROUS_PATTERNS = ["delete all", "drop table", "rm -rf", "drop database", "format disk"]


@dataclass
class DevPilotContext:
    repository_id: uuid.UUID
    snapshot_id: uuid.UUID | None
    prompt: str
    relevant_files: list[str] = field(default_factory=list)
    relevant_symbols: list[dict[str, Any]] = field(default_factory=list)
    graph_dependents: list[dict[str, Any]] = field(default_factory=list)
    existing_tests: list[str] = field(default_factory=list)
    context_markdown: str = ""
    is_ambiguous: bool = False
    clarification_prompt: str | None = None
    is_dangerous: bool = False


class RepositoryContextBuilder:
    """
    Builds repository context for DevPilot by combining:
    1. Phase 9 Semantic Retrieval + Context Assembly.
    2. Phase 10 Knowledge Graph Relationships (callers, extensions, endpoints).
    3. Phase 8 AST Symbols & Code Declarations.
    4. Task ambiguity and danger detection.
    """

    def __init__(
        self,
        graph_provider: BaseGraphProvider | None = None,
        search_engine: SemanticRetrievalEngine | None = None,
        max_context_chars: int = MAX_DEV_PILOT_CONTEXT_CHARS,
    ) -> None:
        self.graph_provider = graph_provider or get_graph_provider()
        self.search_engine = search_engine or SemanticRetrievalEngine()
        self.context_assembler = ContextAssemblyEngine(max_context_chars=max_context_chars)
        self.max_context_chars = max_context_chars

    async def build_context(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        repository_id: uuid.UUID,
        prompt: str,
        snapshot_id: uuid.UUID | None = None,
    ) -> DevPilotContext:
        """
        Assemble comprehensive, bounded context for an engineering task.
        """
        clean_prompt = prompt.strip()

        # 1. Ambiguity & Danger Checks
        is_dangerous = any(pat in clean_prompt.lower() for pat in DANGEROUS_PATTERNS)
        is_ambiguous = (
            len(clean_prompt) < 10
            or clean_prompt.lower() in AMBIGUOUS_PROMPTS
            or len(clean_prompt.split()) < 3
        )

        clarification_msg = None
        if is_dangerous:
            clarification_msg = (
                "The requested operation appears potentially destructive. "
                "Please clarify the specific files or scope of the requested change."
            )
        elif is_ambiguous:
            clarification_msg = (
                "The task description is too general. "
                "Please specify the module, feature, or target behavior to implement."
            )

        # 2. Resolve Snapshot if not provided
        if not snapshot_id:
            snap_stmt = (
                select(RepositorySnapshot)
                .where(RepositorySnapshot.repository_id == repository_id)
                .order_by(desc(RepositorySnapshot.created_at))
                .limit(1)
            )
            snap_res = await db.execute(snap_stmt)
            latest_snap = snap_res.scalar_one_or_none()
            if latest_snap:
                snapshot_id = latest_snap.id

        relevant_files: list[str] = []
        relevant_symbols: list[dict[str, Any]] = []
        graph_dependents: list[dict[str, Any]] = []
        existing_tests: list[str] = []
        markdown_sections: list[str] = [
            f"# DevPilot Repository Context\n**Task Request**: {clean_prompt}\n"
        ]

        # 3. Discover Existing Test Files
        if snapshot_id:
            f_stmt = select(RepositoryFile).where(RepositoryFile.snapshot_id == snapshot_id)
            f_res = await db.execute(f_stmt)
            for f in f_res.scalars().all():
                p = f.path.replace("\\", "/")
                if (
                    "/tests/" in p
                    or p.startswith("tests/")
                    or p.endswith((".test.ts", ".spec.ts", "_test.py", "_test.go"))
                ):
                    existing_tests.append(p)

        # 4. Phase 9 Semantic Retrieval
        try:
            chunks = await self.search_engine.search(
                db=db,
                workspace_id=workspace_id,
                repository_id=repository_id,
                query=clean_prompt,
                limit=10,
            )
            if chunks:
                assembled = self.context_assembler.assemble(
                    repository_id=repository_id,
                    repository_name=f"Repo-{repository_id}",
                    query=clean_prompt,
                    retrieved_chunks=chunks,
                    max_chars=self.max_context_chars // 2,
                )
                markdown_sections.append(assembled.formatted_context_markdown)
                for blk in assembled.blocks:
                    if blk.file_path not in relevant_files:
                        relevant_files.append(blk.file_path)
                    if blk.symbol_name:
                        relevant_symbols.append(
                            {
                                "name": blk.symbol_name,
                                "type": blk.symbol_type or "symbol",
                                "file_path": blk.file_path,
                                "start_line": blk.start_line,
                                "end_line": blk.end_line,
                                "similarity_score": blk.similarity_score,
                            }
                        )
        except Exception as e:
            logger.warning(f"Semantic search failed during context building: {e}")

        # 5. Phase 10 Knowledge Graph Relationships
        if snapshot_id and relevant_symbols and self.graph_provider:
            try:
                query_engine = GraphQueryEngine(self.graph_provider)
                for sym in relevant_symbols[:5]:
                    sym_id = sym.get("id") or sym.get("name", "")
                    callers = await query_engine.find_callers(
                        snapshot_id=str(snapshot_id),
                        target_symbol_id=str(sym_id),
                    )
                    for rec in callers:
                        caller_obj = rec.get("caller")
                        if isinstance(caller_obj, dict):
                            c_name = caller_obj.get("name", "")
                            c_label = caller_obj.get("label", "CodeEntity")
                            props = caller_obj.get("properties", {})
                            c_file = props.get("file_path", "")
                        else:
                            c_name = getattr(caller_obj, "name", str(caller_obj))
                            c_label = getattr(caller_obj, "label", "CodeEntity")
                            props = getattr(caller_obj, "properties", {})
                            c_file = props.get("file_path", "") if isinstance(props, dict) else ""

                        caller_info = {
                            "name": c_name,
                            "label": c_label,
                            "file_path": c_file,
                            "relationship": "CALLS",
                            "target_symbol": sym["name"],
                        }
                        graph_dependents.append(caller_info)
                        if c_file and c_file not in relevant_files:
                            relevant_files.append(c_file)
            except Exception as e:
                logger.warning(f"Graph traversal failed during context building: {e}")

        # 6. Fallback AST Symbols from DB if semantic search had no matches
        if not relevant_symbols and snapshot_id:
            sym_stmt = select(CodeSymbol).where(CodeSymbol.snapshot_id == snapshot_id).limit(20)
            sym_res = await db.execute(sym_stmt)
            for s in sym_res.scalars().all():
                relevant_symbols.append(
                    {
                        "name": s.name,
                        "type": s.symbol_type,
                        "file_path": s.file_path,
                        "start_line": s.start_line,
                        "end_line": s.end_line,
                        "similarity_score": 0.5,
                    }
                )
                if s.file_path not in relevant_files:
                    relevant_files.append(s.file_path)

        # 7. Format Graph & Test Summary in Markdown
        if graph_dependents:
            markdown_sections.append("\n## Knowledge Graph Dependencies:")
            for dep in graph_dependents[:10]:
                markdown_sections.append(
                    f"- `{dep['name']}` ({dep['label']}) in `{dep['file_path']}` {dep['relationship']} `{dep['target_symbol']}`"
                )

        if existing_tests:
            markdown_sections.append(
                f"\n## Existing Test Files ({len(existing_tests)} discovered):"
            )
            for t in existing_tests[:8]:
                markdown_sections.append(f"- `{t}`")

        # 8. DevMemory persistent engineering memory integration
        try:
            from app.db.models.devmemory import MemoryConsumerAgent
            from app.services.devmemory.agent_interface import AgentMemoryInterface

            memory_iface = AgentMemoryInterface()
            mem_context = await memory_iface.build_agent_context(
                db=db,
                workspace_id=workspace_id,
                query=clean_prompt,
                repository_id=repository_id,
                agent=MemoryConsumerAgent.DEVPILOT,
                max_tokens=1000,
            )
            if mem_context and "No prior engineering memories found" not in mem_context:
                markdown_sections.append(f"\n{mem_context}")
        except Exception as e:
            logger.warning(f"DevMemory context assembly skipped safely: {e}")

        context_md = "\n".join(markdown_sections)[: self.max_context_chars]

        return DevPilotContext(
            repository_id=repository_id,
            snapshot_id=snapshot_id,
            prompt=clean_prompt,
            relevant_files=relevant_files,
            relevant_symbols=relevant_symbols,
            graph_dependents=graph_dependents,
            existing_tests=existing_tests,
            context_markdown=context_md,
            is_ambiguous=is_ambiguous,
            clarification_prompt=clarification_msg,
            is_dangerous=is_dangerous,
        )
