from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.devmemory import (
    EngineeringMemory,
    EvidenceType,
    MemoryConsumerAgent,
    MemorySourceType,
    MemoryType,
)
from app.services.devmemory.memory_context import DevMemoryContextBuilder
from app.services.devmemory.memory_graph import DevMemoryGraphService
from app.services.devmemory.memory_retrieval import DevMemoryRetrievalService
from app.services.devmemory.memory_service import DevMemoryService
from app.services.devmemory.schemas import (
    MemoryContextRequest,
    MemoryCreateRequest,
    MemoryEvidenceCreateRequest,
    MemorySearchRequest,
    MemorySearchResult,
)

logger = logging.getLogger("orchestrix.devmemory.agent_interface")


class AgentMemoryInterface:
    """
    Standardized, high-level interface for Orchestrix AI autonomous agents:
    - DevPilot
    - ImpactMind
    - TestPilot
    - SecureFlow
    - FlowForge

    Guarantees:
    - Transparent tenant isolation (scoped by workspace_id and repository_id).
    - Unverified by default for all agent-generated knowledge.
    - Graceful degradation: retrieval or persistence failures never crash primary agent workflows.
    - Context assembly with bounded token ceilings.
    """

    def __init__(
        self,
        memory_service: DevMemoryService | None = None,
        retrieval_service: DevMemoryRetrievalService | None = None,
        context_builder: DevMemoryContextBuilder | None = None,
        graph_service: DevMemoryGraphService | None = None,
    ) -> None:
        self.memory_service = memory_service or DevMemoryService()
        self.retrieval_service = retrieval_service or DevMemoryRetrievalService()
        self.context_builder = context_builder or DevMemoryContextBuilder(self.retrieval_service)
        self.graph_service = graph_service or DevMemoryGraphService()

    async def search_memories(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        query: str,
        repository_id: uuid.UUID | None = None,
        consumer: MemoryConsumerAgent = MemoryConsumerAgent.USER,
        limit: int = 5,
    ) -> list[MemorySearchResult]:
        """Safely search engineering memories for agent context."""
        try:
            req = MemorySearchRequest(
                query=query,
                repository_id=repository_id,
                limit=limit,
                include_archived=False,
                include_outdated=False,
            )
            return await self.retrieval_service.search(db, workspace_id, req, consumer=consumer)
        except Exception as e:
            logger.error(f"Agent memory search failed safely: {e}")
            return []

    async def build_agent_context(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        query: str,
        repository_id: uuid.UUID | None = None,
        agent: MemoryConsumerAgent = MemoryConsumerAgent.DEVPILOT,
        max_tokens: int = 1500,
    ) -> str:
        """Assemble safe formatted markdown prompt context block for the agent."""
        try:
            req = MemoryContextRequest(
                query=query,
                repository_id=repository_id,
                agent=agent,
                max_tokens=max_tokens,
                include_unverified=False,
            )
            resp = await self.context_builder.build_context(db, workspace_id, req)
            return resp.context_markdown
        except Exception as e:
            logger.error(f"Agent memory context assembly failed safely: {e}")
            return "*Engineering memory context temporarily unavailable.*"

    async def record_solution(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        title: str,
        solution_content: str,
        memory_type: MemoryType = MemoryType.VERIFIED_SOLUTION,
        repository_id: uuid.UUID | None = None,
        agent: MemoryConsumerAgent = MemoryConsumerAgent.DEVPILOT,
        evidence_content: str | None = None,
        evidence_type: EvidenceType = EvidenceType.CODE_DIFF,
        source_reference: str | None = None,
    ) -> EngineeringMemory | None:
        """
        Record a discovered solution or decision from agent execution.
        Defaults strictly to UNVERIFIED status until validated by tests or human review.
        """
        try:
            evidence_list = []
            if evidence_content:
                evidence_list.append(
                    MemoryEvidenceCreateRequest(
                        evidence_type=evidence_type,
                        source_reference=source_reference,
                        evidence_content=evidence_content,
                    )
                )

            req = MemoryCreateRequest(
                repository_id=repository_id,
                memory_type=memory_type,
                title=title,
                content=solution_content,
                source_type=MemorySourceType.AGENT_EXECUTION,
                source_reference=source_reference or f"Agent:{agent.value}",
                confidence_score=0.9,
                evidence=evidence_list,
            )
            return await self.memory_service.create_memory(db, workspace_id, req)
        except Exception as e:
            logger.error(f"Failed to record agent solution: {e}")
            return None
