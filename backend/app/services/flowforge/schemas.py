from __future__ import annotations

import enum
from typing import Any

from pydantic import BaseModel, Field


class WorkflowNodeType(enum.StrEnum):
    TRIGGER = "TRIGGER"
    DEVPILOT = "DEVPILOT"
    IMPACTMIND = "IMPACTMIND"
    TESTPILOT = "TESTPILOT"
    SECUREFLOW = "SECUREFLOW"
    CONDITION = "CONDITION"
    APPROVAL = "APPROVAL"
    PARALLEL = "PARALLEL"
    MERGE = "MERGE"
    NOTIFICATION = "NOTIFICATION"
    END = "END"


class WorkflowValidationSeverity(enum.StrEnum):
    ERROR = "ERROR"
    WARNING = "WARNING"


class WorkflowValidationIssue(BaseModel):
    severity: WorkflowValidationSeverity = WorkflowValidationSeverity.ERROR
    code: str
    message: str
    node_id: str | None = None
    target_node_id: str | None = None


class WorkflowValidationResult(BaseModel):
    is_valid: bool
    issues: list[WorkflowValidationIssue] = Field(default_factory=list)
    entry_node_id: str | None = None
    node_count: int = 0
    connection_count: int = 0


class WorkflowNodeConnection(BaseModel):
    source_node_id: str
    target_node_id: str
    condition_branch: str | None = None  # e.g., "true", "false", "default" for CONDITION nodes


class WorkflowNodeDefinition(BaseModel):
    id: str
    name: str | None = None
    node_type: WorkflowNodeType
    config: dict[str, Any] = Field(default_factory=dict)


class WorkflowGraphDefinition(BaseModel):
    nodes: list[WorkflowNodeDefinition] = Field(default_factory=list)
    connections: list[WorkflowNodeConnection] = Field(default_factory=list)
