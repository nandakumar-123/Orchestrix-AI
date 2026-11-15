from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.base import utc_now
from app.db.models.flowforge import (
    WorkflowDefinition,
    WorkflowStatus,
    WorkflowVersion,
)
from app.services.flowforge.schemas import WorkflowValidationResult
from app.services.flowforge.validator import WorkflowValidationError, WorkflowValidator

logger = logging.getLogger("orchestrix.flowforge.definition_service")


class WorkflowDefinitionService:
    """
    Manages FlowForge workflow definitions and versioned immutable snapshots.
    Guarantees:
    - Tenant workspace isolation
    - Validations on create and draft update
    - Immutable versions with monotonically increasing version numbers
    - Safe activation, pause, and archive state transitions
    """

    def __init__(self, validator: WorkflowValidator | None = None) -> None:
        self.validator = validator or WorkflowValidator()

    async def create_workflow(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID | None,
        name: str,
        description: str | None = None,
        definition_json: dict[str, Any] | None = None,
    ) -> tuple[WorkflowDefinition, WorkflowVersion]:
        """
        Create a new workflow definition with an initial version (version 1).
        Validates graph structure if definition_json is provided.
        """
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Workflow name cannot be empty.")

        # Check unique name per workspace
        existing_stmt = select(WorkflowDefinition.id).where(
            WorkflowDefinition.workspace_id == workspace_id,
            WorkflowDefinition.name == clean_name,
        )
        existing = await db.execute(existing_stmt)
        if existing.scalar_one_or_none():
            raise ValueError(f"Workflow with name '{clean_name}' already exists in workspace.")

        initial_graph = definition_json or {
            "nodes": [
                {"id": "trigger_1", "name": "Start", "node_type": "TRIGGER", "config": {}},
                {"id": "end_1", "name": "End", "node_type": "END", "config": {}},
            ],
            "connections": [{"source_node_id": "trigger_1", "target_node_id": "end_1"}],
        }

        # Validate graph
        val_result = self.validator.validate_graph(initial_graph)
        if not val_result.is_valid:
            err_msgs = "; ".join(f"[{i.code}] {i.message}" for i in val_result.issues)
            raise WorkflowValidationError(
                f"Invalid workflow graph: {err_msgs}", issues=val_result.issues
            )

        workflow = WorkflowDefinition(
            workspace_id=workspace_id,
            name=clean_name,
            description=description.strip() if description else None,
            status=WorkflowStatus.DRAFT,
            created_by=user_id,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        db.add(workflow)
        await db.flush()

        initial_version = WorkflowVersion(
            workflow_id=workflow.id,
            workspace_id=workspace_id,
            version_number=1,
            workflow_definition_json=initial_graph,
            description="Initial version",
            created_by=user_id,
            created_at=utc_now(),
        )
        db.add(initial_version)
        await db.flush()

        return workflow, initial_version

    async def get_workflow(
        self,
        db: AsyncSession,
        workflow_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> WorkflowDefinition | None:
        """Retrieve workflow ensuring workspace tenant scoping."""
        stmt = (
            select(WorkflowDefinition)
            .where(
                WorkflowDefinition.id == workflow_id,
                WorkflowDefinition.workspace_id == workspace_id,
            )
            .options(
                selectinload(WorkflowDefinition.versions),
                selectinload(WorkflowDefinition.triggers),
            )
        )
        res = await db.execute(stmt)
        return res.scalar_one_or_none()

    async def list_workflows(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[WorkflowDefinition], int]:
        """List workflows within a workspace with optional status filter and total count."""
        base_query = select(WorkflowDefinition).where(
            WorkflowDefinition.workspace_id == workspace_id
        )
        count_query = select(func.count(WorkflowDefinition.id)).where(
            WorkflowDefinition.workspace_id == workspace_id
        )

        if status:
            base_query = base_query.where(WorkflowDefinition.status == status.upper())
            count_query = count_query.where(WorkflowDefinition.status == status.upper())

        total = (await db.execute(count_query)).scalar_one()

        stmt = (
            base_query.order_by(desc(WorkflowDefinition.updated_at))
            .limit(limit)
            .offset(offset)
            .options(selectinload(WorkflowDefinition.versions))
        )
        items = list((await db.execute(stmt)).scalars().all())
        return items, total

    async def update_draft(
        self,
        db: AsyncSession,
        workflow_id: uuid.UUID,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID | None,
        name: str | None = None,
        description: str | None = None,
        definition_json: dict[str, Any] | None = None,
    ) -> tuple[WorkflowDefinition, WorkflowVersion | None]:
        """
        Update workflow definition metadata or draft graph.
        If definition_json is provided and valid, creates a new version if changed or updates latest draft.
        """
        workflow = await self.get_workflow(db, workflow_id, workspace_id)
        if not workflow:
            raise ValueError(f"Workflow {workflow_id} not found in workspace.")

        if name is not None:
            clean_name = name.strip()
            if not clean_name:
                raise ValueError("Workflow name cannot be empty.")
            # Check unique name conflict
            if clean_name != workflow.name:
                existing_stmt = select(WorkflowDefinition.id).where(
                    WorkflowDefinition.workspace_id == workspace_id,
                    WorkflowDefinition.name == clean_name,
                    WorkflowDefinition.id != workflow_id,
                )
                if (await db.execute(existing_stmt)).scalar_one_or_none():
                    raise ValueError(f"Workflow with name '{clean_name}' already exists.")
            workflow.name = clean_name

        if description is not None:
            workflow.description = description.strip() if description else None

        new_version: WorkflowVersion | None = None

        if definition_json is not None:
            val_result = self.validator.validate_graph(definition_json)
            if not val_result.is_valid:
                err_msgs = "; ".join(f"[{i.code}] {i.message}" for i in val_result.issues)
                raise WorkflowValidationError(
                    f"Invalid workflow graph: {err_msgs}", issues=val_result.issues
                )

            # Get latest version number
            latest_ver_stmt = select(func.max(WorkflowVersion.version_number)).where(
                WorkflowVersion.workflow_id == workflow_id,
                WorkflowVersion.workspace_id == workspace_id,
            )
            max_ver = (await db.execute(latest_ver_stmt)).scalar_one_or_none() or 0
            new_version_num = max_ver + 1

            new_version = WorkflowVersion(
                workflow_id=workflow_id,
                workspace_id=workspace_id,
                version_number=new_version_num,
                workflow_definition_json=definition_json,
                description=f"Draft update v{new_version_num}",
                created_by=user_id,
                created_at=utc_now(),
            )
            db.add(new_version)

        workflow.updated_at = utc_now()
        await db.flush()
        return workflow, new_version

    async def activate_workflow(
        self,
        db: AsyncSession,
        workflow_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> WorkflowDefinition:
        """Activate workflow making it eligible for execution."""
        workflow = await self.get_workflow(db, workflow_id, workspace_id)
        if not workflow:
            raise ValueError(f"Workflow {workflow_id} not found in workspace.")

        if not workflow.versions:
            raise ValueError("Cannot activate a workflow with no versions.")

        # Ensure latest version is valid
        latest_version = max(workflow.versions, key=lambda v: v.version_number)
        val = self.validator.validate_graph(latest_version.workflow_definition_json)
        if not val.is_valid:
            err_msgs = "; ".join(f"[{i.code}] {i.message}" for i in val.issues)
            raise WorkflowValidationError(
                f"Cannot activate invalid workflow: {err_msgs}", issues=val.issues
            )

        workflow.status = WorkflowStatus.ACTIVE
        workflow.updated_at = utc_now()
        await db.flush()
        return workflow

    async def pause_workflow(
        self,
        db: AsyncSession,
        workflow_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> WorkflowDefinition:
        """Pause an active workflow."""
        workflow = await self.get_workflow(db, workflow_id, workspace_id)
        if not workflow:
            raise ValueError(f"Workflow {workflow_id} not found in workspace.")

        workflow.status = WorkflowStatus.PAUSED
        workflow.updated_at = utc_now()
        await db.flush()
        return workflow

    async def archive_workflow(
        self,
        db: AsyncSession,
        workflow_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> WorkflowDefinition:
        """Archive a workflow."""
        workflow = await self.get_workflow(db, workflow_id, workspace_id)
        if not workflow:
            raise ValueError(f"Workflow {workflow_id} not found in workspace.")

        workflow.status = WorkflowStatus.ARCHIVED
        workflow.updated_at = utc_now()
        await db.flush()
        return workflow

    async def create_version(
        self,
        db: AsyncSession,
        workflow_id: uuid.UUID,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID | None,
        definition_json: dict[str, Any],
        description: str | None = None,
    ) -> WorkflowVersion:
        """Explicitly publish a new immutable version of the workflow."""
        workflow = await self.get_workflow(db, workflow_id, workspace_id)
        if not workflow:
            raise ValueError(f"Workflow {workflow_id} not found in workspace.")

        val_result = self.validator.validate_graph(definition_json)
        if not val_result.is_valid:
            err_msgs = "; ".join(f"[{i.code}] {i.message}" for i in val_result.issues)
            raise WorkflowValidationError(
                f"Invalid workflow graph: {err_msgs}", issues=val_result.issues
            )

        latest_ver_stmt = select(func.max(WorkflowVersion.version_number)).where(
            WorkflowVersion.workflow_id == workflow_id,
            WorkflowVersion.workspace_id == workspace_id,
        )
        max_ver = (await db.execute(latest_ver_stmt)).scalar_one_or_none() or 0
        new_version_num = max_ver + 1

        version = WorkflowVersion(
            workflow_id=workflow_id,
            workspace_id=workspace_id,
            version_number=new_version_num,
            workflow_definition_json=definition_json,
            description=description or f"Version {new_version_num}",
            created_by=user_id,
            created_at=utc_now(),
        )
        db.add(version)
        workflow.updated_at = utc_now()
        await db.flush()
        return version

    async def list_versions(
        self,
        db: AsyncSession,
        workflow_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> list[WorkflowVersion]:
        """Retrieve all versions of a workflow in descending version order."""
        stmt = (
            select(WorkflowVersion)
            .where(
                WorkflowVersion.workflow_id == workflow_id,
                WorkflowVersion.workspace_id == workspace_id,
            )
            .order_by(desc(WorkflowVersion.version_number))
        )
        res = await db.execute(stmt)
        return list(res.scalars().all())

    async def get_version(
        self,
        db: AsyncSession,
        workflow_id: uuid.UUID,
        version_id_or_number: uuid.UUID | int,
        workspace_id: uuid.UUID,
    ) -> WorkflowVersion | None:
        """Get a specific workflow version by UUID or version number."""
        stmt = select(WorkflowVersion).where(
            WorkflowVersion.workflow_id == workflow_id,
            WorkflowVersion.workspace_id == workspace_id,
        )
        if isinstance(version_id_or_number, int):
            stmt = stmt.where(WorkflowVersion.version_number == version_id_or_number)
        else:
            stmt = stmt.where(WorkflowVersion.id == version_id_or_number)

        res = await db.execute(stmt)
        return res.scalar_one_or_none()

    def validate_workflow_json(self, definition_json: dict[str, Any]) -> WorkflowValidationResult:
        """Convenience method to validate workflow graph definition without saving."""
        return self.validator.validate_graph(definition_json)
