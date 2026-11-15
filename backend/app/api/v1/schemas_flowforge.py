from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class WorkflowCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    definition: dict[str, Any] | None = None


class WorkflowUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    definition: dict[str, Any] | None = None


class WorkflowVersionCreateRequest(BaseModel):
    definition: dict[str, Any]
    description: str | None = None


class WorkflowValidateRequest(BaseModel):
    definition: dict[str, Any]


class WorkflowExecuteRequest(BaseModel):
    workflow_version_id: uuid.UUID | None = None
    trigger_id: uuid.UUID | None = None
    context_data: dict[str, Any] = Field(default_factory=dict)


class WorkflowExecutionCancelRequest(BaseModel):
    reason: str | None = None


class WorkflowApprovalDecisionRequest(BaseModel):
    decision_reason: str | None = None


class WorkflowVersionResponse(BaseModel):
    id: uuid.UUID
    workflow_id: uuid.UUID
    workspace_id: uuid.UUID
    version_number: int
    workflow_definition_json: dict[str, Any]
    description: str | None
    created_by: uuid.UUID | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WorkflowResponse(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    description: str | None
    status: str
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    latest_version: WorkflowVersionResponse | None = None

    model_config = ConfigDict(from_attributes=True)


class WorkflowListResponse(BaseModel):
    items: list[WorkflowResponse]
    total: int
    limit: int
    offset: int


class WorkflowStepExecutionResponse(BaseModel):
    id: uuid.UUID
    execution_id: uuid.UUID
    workspace_id: uuid.UUID
    node_id: str
    node_name: str | None
    agent_type: str | None
    status: str
    input_reference: dict[str, Any] | None
    output_reference: dict[str, Any] | None
    attempt_number: int
    started_at: datetime | None
    completed_at: datetime | None
    error_summary: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WorkflowApprovalResponse(BaseModel):
    id: uuid.UUID
    execution_id: uuid.UUID
    step_execution_id: uuid.UUID
    workspace_id: uuid.UUID
    requested_by: uuid.UUID | None
    approved_by: uuid.UUID | None
    status: str
    decision_reason: str | None
    created_at: datetime
    decided_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class WorkflowEventResponse(BaseModel):
    id: uuid.UUID
    execution_id: uuid.UUID
    workspace_id: uuid.UUID
    event_type: str
    payload_json: dict[str, Any] | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WorkflowExecutionResponse(BaseModel):
    id: uuid.UUID
    workflow_id: uuid.UUID
    workflow_version_id: uuid.UUID
    workspace_id: uuid.UUID
    trigger_id: uuid.UUID | None
    status: str
    context_data: dict[str, Any] | None
    started_at: datetime | None
    completed_at: datetime | None
    error_summary: str | None
    created_at: datetime
    steps: list[WorkflowStepExecutionResponse] = Field(default_factory=list)
    approvals: list[WorkflowApprovalResponse] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class WorkflowExecutionListResponse(BaseModel):
    items: list[WorkflowExecutionResponse]
    total: int
    limit: int
    offset: int
