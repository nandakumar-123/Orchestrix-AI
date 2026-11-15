from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.db.models.devmemory import (
    EvidenceType,
    MemoryConsumerAgent,
    MemoryRelationshipType,
    MemorySourceType,
    MemoryType,
    MemoryVerificationStatus,
)


class MemoryEvidenceCreateRequest(BaseModel):
    evidence_type: EvidenceType
    source_reference: str | None = Field(default=None, max_length=1024)
    evidence_content: str = Field(..., min_length=1, max_length=100000)


class MemoryEvidenceResponse(BaseModel):
    id: uuid.UUID
    memory_id: uuid.UUID
    workspace_id: uuid.UUID
    evidence_type: str
    source_reference: str | None
    evidence_content: str
    created_at: datetime

    model_config = {"from_attributes": True}


class MemoryCreateRequest(BaseModel):
    repository_id: uuid.UUID | None = None
    memory_type: MemoryType
    title: str = Field(..., min_length=1, max_length=512)
    content: str = Field(..., min_length=1, max_length=100000)
    summary: str | None = Field(default=None, max_length=4096)
    source_type: MemorySourceType = MemorySourceType.USER_INPUT
    source_reference: str | None = Field(default=None, max_length=1024)
    confidence_score: float = Field(default=1.0, ge=0.0, le=1.0)
    metadata: dict[str, Any] | None = None
    evidence: list[MemoryEvidenceCreateRequest] | None = None


class MemoryUpdateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=512)
    content: str | None = Field(default=None, max_length=100000)
    summary: str | None = Field(default=None, max_length=4096)
    confidence_score: float | None = Field(default=None, ge=0.0, le=1.0)
    metadata: dict[str, Any] | None = None


class MemoryVerifyRequest(BaseModel):
    evidence: MemoryEvidenceCreateRequest | None = None
    reason: str | None = Field(default=None, max_length=1024)


class MemoryOutdateRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=1024)


class MemoryRelationshipCreateRequest(BaseModel):
    source_memory_id: uuid.UUID
    target_memory_id: uuid.UUID
    relationship_type: MemoryRelationshipType
    confidence_score: float = Field(default=1.0, ge=0.0, le=1.0)
    metadata: dict[str, Any] | None = None


class MemoryRelationshipResponse(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    source_memory_id: uuid.UUID
    target_memory_id: uuid.UUID
    relationship_type: str
    confidence_score: float
    created_at: datetime
    metadata: dict[str, Any] | None = Field(default=None, alias="metadata_")

    model_config = {"from_attributes": True, "populate_by_name": True}


class MemoryResponse(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    repository_id: uuid.UUID | None
    memory_type: str
    title: str
    content: str
    summary: str | None
    source_type: str
    source_reference: str | None
    confidence_score: float
    verification_status: str
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None
    content_hash: str
    metadata: dict[str, Any] | None = Field(default=None, alias="metadata_")
    evidence: list[MemoryEvidenceResponse] = Field(default_factory=list)

    model_config = {"from_attributes": True, "populate_by_name": True}


class MemorySearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    repository_id: uuid.UUID | None = None
    memory_types: list[MemoryType] | None = None
    verification_statuses: list[MemoryVerificationStatus] | None = None
    include_archived: bool = False
    include_outdated: bool = False
    limit: int = Field(default=10, ge=1, le=100)
    min_score: float = Field(default=0.0, ge=0.0, le=1.0)
    hybrid_weight_semantic: float = Field(default=0.7, ge=0.0, le=1.0)
    hybrid_weight_lexical: float = Field(default=0.3, ge=0.0, le=1.0)


class MemorySearchResult(BaseModel):
    memory: MemoryResponse
    relevance_score: float
    semantic_score: float
    lexical_score: float
    is_verified: bool
    evidence_count: int


class MemoryContextRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    repository_id: uuid.UUID | None = None
    agent: MemoryConsumerAgent = MemoryConsumerAgent.USER
    max_tokens: int = Field(default=2000, ge=100, le=8000)
    include_unverified: bool = False
    limit: int = Field(default=5, ge=1, le=20)


class MemoryContextResponse(BaseModel):
    context_markdown: str
    citations: list[uuid.UUID]
    memories_used: int
    verified_count: int
    unverified_count: int


class GraphSyncResponse(BaseModel):
    synced_nodes: int
    synced_relationships: int
    workspace_id: uuid.UUID
    status: str
    message: str | None = None
