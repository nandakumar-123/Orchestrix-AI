from __future__ import annotations

import hashlib
import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.base import utc_now
from app.db.models.devmemory import (
    EngineeringMemory,
    MemoryAccessLog,
    MemoryAccessType,
    MemoryConsumerAgent,
    MemoryEvidence,
    MemoryRelationship,
    MemoryRelationshipType,
    MemoryVerificationStatus,
)
from app.db.models.repository import Repository
from app.services.devmemory.schemas import (
    MemoryCreateRequest,
    MemoryEvidenceCreateRequest,
    MemoryRelationshipCreateRequest,
    MemoryUpdateRequest,
)
from app.services.embedding_service import get_embedding_provider
from app.services.secureflow.redaction import redact_secrets

logger = logging.getLogger("orchestrix.devmemory.service")


class MemoryServiceError(Exception):
    """Base error for DevMemory operations."""

    pass


class MemoryNotFoundError(MemoryServiceError):
    """Raised when memory does not exist or workspace mismatch."""

    pass


class DuplicateMemoryError(MemoryServiceError):
    """Raised when an identical memory already exists."""

    def __init__(self, message: str, memory_id: uuid.UUID | None = None) -> None:
        super().__init__(message)
        self.memory_id = memory_id


class InvalidMemoryTransitionError(MemoryServiceError):
    """Raised on invalid lifecycle transition."""

    pass


class TenantBoundaryViolationError(MemoryServiceError):
    """Raised when cross-workspace linkage is attempted."""

    pass


def compute_content_hash(
    workspace_id: uuid.UUID,
    memory_type: str,
    content: str,
    repository_id: uuid.UUID | None = None,
) -> str:
    """
    Deterministic normalized content hash scoped to workspace, memory type, and optional repository.
    - Workspace-wide memories (repository_id is None) share an explicit ':workspace:' namespace.
    - Repository-specific memories include the repository UUID to prevent identical content in
      two different repositories from colliding or leaking knowledge across repositories.
    """
    normalized = " ".join(content.strip().split())
    repo_scope = str(repository_id) if repository_id else "workspace"
    raw = f"{workspace_id}:{repo_scope}:{memory_type}:{normalized}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class DevMemoryService:
    """
    Core persistence, verification, and lifecycle management service for DevMemory.
    Ensures:
    - Zero cross-workspace memory or evidence leakage.
    - Full secret redaction before persistence and embedding.
    - Bounded deduplication with idempotent returns.
    - Evidence-anchored verification lifecycle.
    - Safe archival without physical data destruction.
    """

    def __init__(self) -> None:
        self._embedding_provider = None

    def _get_embedding_provider(self):
        if self._embedding_provider is None:
            self._embedding_provider = get_embedding_provider()
        return self._embedding_provider

    async def create_memory(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        request: MemoryCreateRequest,
        created_by: uuid.UUID | None = None,
    ) -> EngineeringMemory:
        """Create a new engineering memory with initial UNVERIFIED lifecycle."""
        # 1. Repository tenant isolation validation
        if request.repository_id:
            repo = await db.get(Repository, request.repository_id)
            if not repo or repo.workspace_id != workspace_id:
                raise TenantBoundaryViolationError(
                    f"Repository {request.repository_id} does not belong to workspace {workspace_id}."
                )

        # 2. Secret Redaction
        clean_title = redact_secrets(request.title.strip())
        clean_content = redact_secrets(request.content.strip())
        clean_summary = redact_secrets(request.summary.strip()) if request.summary else None
        clean_ref = (
            redact_secrets(request.source_reference.strip()) if request.source_reference else None
        )

        # 3. Content normalization and hash deduplication (repository-aware)
        c_hash = compute_content_hash(
            workspace_id,
            request.memory_type.value,
            clean_content,
            repository_id=request.repository_id,
        )

        # 4. Check for existing exact duplicate in same workspace and repository scope
        stmt_dup = (
            select(EngineeringMemory)
            .where(
                EngineeringMemory.workspace_id == workspace_id,
                EngineeringMemory.content_hash == c_hash,
            )
            .options(selectinload(EngineeringMemory.evidence))
        )
        if request.repository_id:
            stmt_dup = stmt_dup.where(EngineeringMemory.repository_id == request.repository_id)
        else:
            stmt_dup = stmt_dup.where(EngineeringMemory.repository_id.is_(None))

        dup = (await db.execute(stmt_dup)).scalar_one_or_none()
        if dup:
            logger.info(
                f"Duplicate memory creation detected for hash {c_hash}, returning existing {dup.id}"
            )
            return dup

        # 5. Embedding generation (CPU-safe, single provider instance)
        embedding_vec: list[float] | None = None
        try:
            embed_text = f"{clean_title}\n\n{clean_content}"
            embedding_vec = await self._get_embedding_provider().embed_query(embed_text)
        except Exception as e:
            logger.warning(f"Embedding generation failed for memory creation: {e}")
            embedding_vec = None

        # 6. Instantiate Memory record
        memory = EngineeringMemory(
            workspace_id=workspace_id,
            repository_id=request.repository_id,
            memory_type=request.memory_type.value,
            title=clean_title,
            content=clean_content,
            summary=clean_summary,
            source_type=request.source_type.value,
            source_reference=clean_ref,
            confidence_score=request.confidence_score,
            verification_status=MemoryVerificationStatus.UNVERIFIED.value,
            created_by=created_by,
            content_hash=c_hash,
            metadata_=request.metadata or {},
            embedding=embedding_vec,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        db.add(memory)
        await db.flush()

        # 7. Attach initial evidence if provided
        if request.evidence:
            for ev_item in request.evidence:
                clean_ev_content = redact_secrets(ev_item.evidence_content)
                clean_ev_ref = redact_secrets(ev_item.source_reference or "") or None
                ev_record = MemoryEvidence(
                    memory_id=memory.id,
                    workspace_id=workspace_id,
                    evidence_type=ev_item.evidence_type.value,
                    source_reference=clean_ev_ref,
                    evidence_content=clean_ev_content,
                    created_at=utc_now(),
                )
                db.add(ev_record)
            await db.flush()

        # 8. Log Access / Creation Audit
        db.add(
            MemoryAccessLog(
                memory_id=memory.id,
                workspace_id=workspace_id,
                agent_type=MemoryConsumerAgent.USER.value
                if created_by
                else MemoryConsumerAgent.DEVPILOT.value,
                access_type=MemoryAccessType.RETRIEVE.value,
                context_metadata={
                    "action": "CREATE",
                    "created_by": str(created_by) if created_by else None,
                },
                accessed_at=utc_now(),
            )
        )
        await db.flush()

        # Refresh with evidence relationship loaded
        res = await db.execute(
            select(EngineeringMemory)
            .where(EngineeringMemory.id == memory.id)
            .options(selectinload(EngineeringMemory.evidence))
        )
        return res.scalar_one()

    async def get_memory(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        memory_id: uuid.UUID,
        consumer: MemoryConsumerAgent = MemoryConsumerAgent.USER,
        log_access: bool = True,
    ) -> EngineeringMemory:
        """Retrieve memory enforcing workspace isolation and audit trail."""
        stmt = (
            select(EngineeringMemory)
            .where(
                EngineeringMemory.id == memory_id,
                EngineeringMemory.workspace_id == workspace_id,
            )
            .options(selectinload(EngineeringMemory.evidence))
        )
        mem = (await db.execute(stmt)).scalar_one_or_none()
        if not mem:
            raise MemoryNotFoundError(f"Memory {memory_id} not found in workspace {workspace_id}.")

        if log_access:
            db.add(
                MemoryAccessLog(
                    memory_id=mem.id,
                    workspace_id=workspace_id,
                    agent_type=consumer.value,
                    access_type=MemoryAccessType.RETRIEVE.value,
                    context_metadata={"action": "GET"},
                    accessed_at=utc_now(),
                )
            )
            await db.flush()

        return mem

    async def update_memory(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        memory_id: uuid.UUID,
        request: MemoryUpdateRequest,
    ) -> EngineeringMemory:
        """Update permitted metadata/content fields with re-embedding and hash recomputation."""
        mem = await self.get_memory(db, workspace_id, memory_id, log_access=False)
        if mem.verification_status == MemoryVerificationStatus.ARCHIVED.value:
            raise InvalidMemoryTransitionError("Cannot update an ARCHIVED memory.")

        has_content_changed = False

        if request.title is not None:
            mem.title = redact_secrets(request.title.strip())
            has_content_changed = True

        if request.content is not None:
            clean_content = redact_secrets(request.content.strip())
            mem.content = clean_content
            mem.content_hash = compute_content_hash(workspace_id, mem.memory_type, clean_content)
            has_content_changed = True

        if request.summary is not None:
            mem.summary = redact_secrets(request.summary.strip())

        if request.confidence_score is not None:
            mem.confidence_score = request.confidence_score

        if request.metadata is not None:
            current_meta = dict(mem.metadata_ or {})
            current_meta.update(request.metadata)
            mem.metadata_ = current_meta

        mem.updated_at = utc_now()

        # If content or title changed, recompute embedding and potentially flag for review
        if has_content_changed:
            try:
                embed_text = f"{mem.title}\n\n{mem.content}"
                mem.embedding = await self._get_embedding_provider().embed_query(embed_text)
            except Exception as e:
                logger.warning(f"Re-embedding failed on memory update: {e}")

        await db.flush()
        return mem

    async def verify_memory(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        memory_id: uuid.UUID,
        evidence: MemoryEvidenceCreateRequest | None = None,
        reason: str | None = None,
        verified_by: uuid.UUID | None = None,
    ) -> EngineeringMemory:
        """
        Transition memory to VERIFIED status with mandatory evidence requirement.
        A memory cannot become VERIFIED purely on ungrounded claims.
        """
        mem = await self.get_memory(db, workspace_id, memory_id, log_access=False)
        if mem.verification_status == MemoryVerificationStatus.ARCHIVED.value:
            raise InvalidMemoryTransitionError("Archived memory cannot be verified directly.")

        # Require existing evidence or new evidence attachment
        if evidence:
            ev_record = MemoryEvidence(
                memory_id=mem.id,
                workspace_id=workspace_id,
                evidence_type=evidence.evidence_type.value,
                source_reference=redact_secrets(evidence.source_reference or "") or None,
                evidence_content=redact_secrets(evidence.evidence_content),
                created_at=utc_now(),
            )
            db.add(ev_record)
            await db.flush()

        # Check total evidence
        stmt_ev_count = select(func.count(MemoryEvidence.id)).where(
            MemoryEvidence.memory_id == mem.id,
            MemoryEvidence.workspace_id == workspace_id,
        )
        ev_count = (await db.execute(stmt_ev_count)).scalar() or 0
        if ev_count == 0:
            raise InvalidMemoryTransitionError(
                "Cannot verify memory: at least one piece of evidence is required."
            )

        mem.verification_status = MemoryVerificationStatus.VERIFIED.value
        mem.updated_at = utc_now()
        meta = dict(mem.metadata_ or {})
        meta["verified_at"] = str(utc_now())
        meta["verified_by"] = str(verified_by) if verified_by else None
        meta["verification_reason"] = reason or "Human or verified test outcome corroboration"
        mem.metadata_ = meta

        db.add(
            MemoryAccessLog(
                memory_id=mem.id,
                workspace_id=workspace_id,
                agent_type=MemoryConsumerAgent.USER.value
                if verified_by
                else MemoryConsumerAgent.DEVPILOT.value,
                access_type=MemoryAccessType.VERIFY.value,
                context_metadata={"action": "VERIFY", "reason": reason},
                accessed_at=utc_now(),
            )
        )
        await db.flush()

        # Re-fetch with fresh relationships to ensure evidence collection is up to date
        await db.refresh(mem)
        res = await db.execute(
            select(EngineeringMemory)
            .where(EngineeringMemory.id == mem.id)
            .options(selectinload(EngineeringMemory.evidence))
            .execution_options(populate_existing=True)
        )
        return res.scalar_one()

    async def mark_outdated(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        memory_id: uuid.UUID,
        reason: str | None = None,
    ) -> EngineeringMemory:
        """Mark memory OUTDATED due to downstream repository code changes."""
        mem = await self.get_memory(db, workspace_id, memory_id, log_access=False)
        if mem.verification_status == MemoryVerificationStatus.ARCHIVED.value:
            raise InvalidMemoryTransitionError("Cannot mark ARCHIVED memory as OUTDATED.")

        mem.verification_status = MemoryVerificationStatus.OUTDATED.value
        mem.updated_at = utc_now()
        meta = dict(mem.metadata_ or {})
        meta["outdated_at"] = str(utc_now())
        meta["outdated_reason"] = reason or "Code changes superseded this knowledge"
        mem.metadata_ = meta

        db.add(
            MemoryAccessLog(
                memory_id=mem.id,
                workspace_id=workspace_id,
                agent_type=MemoryConsumerAgent.USER.value,
                access_type=MemoryAccessType.INVALIDATE.value,
                context_metadata={"action": "OUTDATE", "reason": reason},
                accessed_at=utc_now(),
            )
        )
        await db.flush()
        return mem

    async def archive_memory(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        memory_id: uuid.UUID,
        reason: str | None = None,
    ) -> EngineeringMemory:
        """Archive memory without physical deletion to preserve historical audit trail."""
        mem = await self.get_memory(db, workspace_id, memory_id, log_access=False)
        mem.verification_status = MemoryVerificationStatus.ARCHIVED.value
        mem.updated_at = utc_now()
        meta = dict(mem.metadata_ or {})
        meta["archived_at"] = str(utc_now())
        meta["archived_reason"] = reason or "Archived from active retrieval"
        mem.metadata_ = meta

        db.add(
            MemoryAccessLog(
                memory_id=mem.id,
                workspace_id=workspace_id,
                agent_type=MemoryConsumerAgent.USER.value,
                access_type=MemoryAccessType.INVALIDATE.value,
                context_metadata={"action": "ARCHIVE", "reason": reason},
                accessed_at=utc_now(),
            )
        )
        await db.flush()
        return mem

    async def attach_evidence(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        memory_id: uuid.UUID,
        evidence: MemoryEvidenceCreateRequest,
    ) -> MemoryEvidence:
        """Attach supporting evidence to an existing memory."""
        # Ensure memory exists and belongs to workspace
        mem = await self.get_memory(db, workspace_id, memory_id, log_access=False)
        if mem.verification_status == MemoryVerificationStatus.ARCHIVED.value:
            raise InvalidMemoryTransitionError("Cannot attach evidence to ARCHIVED memory.")

        clean_ev_content = redact_secrets(evidence.evidence_content)
        clean_ev_ref = redact_secrets(evidence.source_reference or "") or None

        record = MemoryEvidence(
            memory_id=mem.id,
            workspace_id=workspace_id,
            evidence_type=evidence.evidence_type.value,
            source_reference=clean_ev_ref,
            evidence_content=clean_ev_content,
            created_at=utc_now(),
        )
        db.add(record)
        await db.flush()
        return record

    async def list_evidence(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        memory_id: uuid.UUID,
    ) -> list[MemoryEvidence]:
        """List all evidence linked to a memory."""
        await self.get_memory(db, workspace_id, memory_id, log_access=False)
        stmt = (
            select(MemoryEvidence)
            .where(
                MemoryEvidence.memory_id == memory_id,
                MemoryEvidence.workspace_id == workspace_id,
            )
            .order_by(MemoryEvidence.created_at.asc())
        )
        res = await db.execute(stmt)
        return list(res.scalars().all())

    async def create_relationship(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        request: MemoryRelationshipCreateRequest,
    ) -> MemoryRelationship:
        """
        Record directional relationship between two memories in the same workspace.
        Rejects cross-workspace relationships at both database and application level.
        """
        if request.source_memory_id == request.target_memory_id:
            raise InvalidMemoryTransitionError(
                "Cannot create a relationship from a memory to itself."
            )

        # Validate both memories exist in this workspace
        source = await self.get_memory(db, workspace_id, request.source_memory_id, log_access=False)
        target = await self.get_memory(db, workspace_id, request.target_memory_id, log_access=False)

        # Contradiction / Supersession rules
        if request.relationship_type == MemoryRelationshipType.SUPERSEDES:
            # If source supersedes target, mark target as OUTDATED if not already archived
            if target.verification_status != MemoryVerificationStatus.ARCHIVED.value:
                target.verification_status = MemoryVerificationStatus.OUTDATED.value
                t_meta = dict(target.metadata_ or {})
                t_meta["superseded_by"] = str(source.id)
                target.metadata_ = t_meta

        # Check existing relationship
        stmt_exist = select(MemoryRelationship).where(
            MemoryRelationship.source_memory_id == source.id,
            MemoryRelationship.target_memory_id == target.id,
            MemoryRelationship.relationship_type == request.relationship_type.value,
            MemoryRelationship.workspace_id == workspace_id,
        )
        existing = (await db.execute(stmt_exist)).scalar_one_or_none()
        if existing:
            return existing

        rel = MemoryRelationship(
            workspace_id=workspace_id,
            source_memory_id=source.id,
            target_memory_id=target.id,
            relationship_type=request.relationship_type.value,
            confidence_score=request.confidence_score,
            created_at=utc_now(),
        )
        db.add(rel)
        await db.flush()
        return rel

    async def list_relationships(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        memory_id: uuid.UUID,
    ) -> list[MemoryRelationship]:
        """List incoming and outgoing relationships for a memory."""
        await self.get_memory(db, workspace_id, memory_id, log_access=False)
        stmt = (
            select(MemoryRelationship)
            .where(
                MemoryRelationship.workspace_id == workspace_id,
                (MemoryRelationship.source_memory_id == memory_id)
                | (MemoryRelationship.target_memory_id == memory_id),
            )
            .order_by(MemoryRelationship.created_at.desc())
        )
        res = await db.execute(stmt)
        return list(res.scalars().all())
