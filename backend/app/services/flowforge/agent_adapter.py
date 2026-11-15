from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.devmemory import MemoryConsumerAgent
from app.db.models.repository import Repository
from app.services.devmemory.memory_context import DevMemoryContextBuilder
from app.services.devmemory.schemas import MemoryContextRequest
from app.services.devpilot.orchestrator import DevPilotOrchestrator
from app.services.impactmind.engine import ImpactMindEngine
from app.services.secureflow.service import SecureFlowService
from app.services.testpilot.service import TestPilotService

logger = logging.getLogger("orchestrix.flowforge.agent_adapter")


class AgentUnavailableError(Exception):
    """Raised when an integrated agent fails to initialize or execute."""

    pass


class FlowForgeAgentAdapter:
    """
    Integrates FlowForge workflow steps with Orchestrix agent engines:
    - DEVPILOT: DevPilot engineering planning, task creation, and code generation.
    - IMPACTMIND: ImpactMind AST & graph change impact analysis.
    - TESTPILOT: TestPilot autonomous test detection, generation, and controlled execution.
    - SECUREFLOW: SecureFlow vulnerability, secret, and SAST scanning.

    Guarantees:
    - Reuses existing agent service interfaces directly.
    - Validates inputs before delegation.
    - Strictly preserves workspace isolation and repository context.
    - Redacts raw secrets from returned output references.
    - Handles unavailable agents gracefully.
    """

    def __init__(
        self,
        devpilot_orchestrator: DevPilotOrchestrator | None = None,
        impactmind_engine: ImpactMindEngine | None = None,
        testpilot_service: TestPilotService | None = None,
        secureflow_service: SecureFlowService | None = None,
        memory_context_builder: DevMemoryContextBuilder | None = None,
    ) -> None:
        self._devpilot = devpilot_orchestrator
        self._impactmind = impactmind_engine
        self._testpilot = testpilot_service
        self._secureflow = secureflow_service
        self._memory_context_builder = memory_context_builder or DevMemoryContextBuilder()

    def get_devpilot(self) -> DevPilotOrchestrator:
        if self._devpilot is None:
            self._devpilot = DevPilotOrchestrator()
        return self._devpilot

    def get_impactmind(self) -> ImpactMindEngine:
        if self._impactmind is None:
            self._impactmind = ImpactMindEngine()
        return self._impactmind

    def get_testpilot(self) -> TestPilotService:
        if self._testpilot is None:
            self._testpilot = TestPilotService()
        return self._testpilot

    def get_secureflow(self) -> SecureFlowService:
        if self._secureflow is None:
            self._secureflow = SecureFlowService()
        return self._secureflow

    async def execute_agent_step(
        self,
        db: AsyncSession,
        agent_type: str,
        workspace_id: uuid.UUID,
        node_id: str,
        config: dict[str, Any],
        context_data: dict[str, Any],
        execution_id: uuid.UUID | None = None,
        attempt_number: int = 1,
    ) -> dict[str, Any]:
        """
        Execute an agent task step, returning an output reference dictionary.
        Outputs are structured metadata references (e.g., task_id, scan_id, execution_id)
        rather than massive blobs or raw secrets.
        Uses execution_id + node_id as the stable idempotency key to avoid cross-task collisions.
        """
        agent_type_upper = agent_type.upper()
        memory_context, memory_reference = await self._retrieve_memory_context(
            db=db,
            agent_type=agent_type_upper,
            workspace_id=workspace_id,
            config=config,
            context_data=context_data,
        )

        if agent_type_upper == "DEVPILOT":
            devpilot_config = dict(config)
            if memory_context:
                base_prompt = str(devpilot_config.get("prompt") or context_data.get("prompt") or "")
                devpilot_config["prompt"] = f"{base_prompt}\n\n{memory_context}".strip()
            result = await self._execute_devpilot(
                db,
                workspace_id,
                node_id,
                devpilot_config,
                context_data,
                execution_id,
                attempt_number,
            )
        elif agent_type_upper == "IMPACTMIND":
            result = await self._execute_impactmind(db, workspace_id, node_id, config, context_data)
        elif agent_type_upper == "TESTPILOT":
            result = await self._execute_testpilot(
                db, workspace_id, node_id, config, context_data, memory_context
            )
        elif agent_type_upper == "SECUREFLOW":
            result = await self._execute_secureflow(db, workspace_id, node_id, config, context_data)
        else:
            raise AgentUnavailableError(f"Unsupported agent type: {agent_type}")

        # Store only durable citations and retrieval metadata.  Prompt text, embeddings,
        # and memory contents must never be persisted in FlowForge execution records.
        result["memory_context"] = memory_reference
        return result

    async def _retrieve_memory_context(
        self,
        db: AsyncSession,
        agent_type: str,
        workspace_id: uuid.UUID,
        config: dict[str, Any],
        context_data: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        """Retrieve verified, tenant-scoped memory without making it a workflow dependency."""
        try:
            repository_id_raw = config.get("repository_id") or context_data.get("repository_id")
            repository_id = uuid.UUID(str(repository_id_raw)) if repository_id_raw else None
            consumer = MemoryConsumerAgent(agent_type)
            query = str(
                config.get("prompt")
                or config.get("title")
                or config.get("task_title")
                or config.get("action")
                or f"FlowForge {agent_type} workflow step"
            )
            response = await self._memory_context_builder.build_context(
                db=db,
                workspace_id=workspace_id,
                request=MemoryContextRequest(
                    query=query,
                    repository_id=repository_id,
                    agent=consumer,
                    include_unverified=False,
                    max_tokens=1000,
                ),
            )
            return response.context_markdown, {
                "status": "RETRIEVED",
                "memory_ids": [str(memory_id) for memory_id in response.citations],
                "memories_used": response.memories_used,
                "verified_count": response.verified_count,
                "unverified_count": response.unverified_count,
                "repository_id": str(repository_id) if repository_id else None,
            }
        except Exception as exc:
            # Memory is advisory.  Record the safe fallback without exposing internals.
            logger.warning(
                "DevMemory retrieval unavailable for FlowForge %s step: %s",
                agent_type,
                type(exc).__name__,
            )
            return "", {"status": "UNAVAILABLE", "reason": type(exc).__name__}

    async def _execute_devpilot(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        node_id: str,
        config: dict[str, Any],
        context_data: dict[str, Any],
        execution_id: uuid.UUID | None = None,
        attempt_number: int = 1,
    ) -> dict[str, Any]:
        repository_id_str = config.get("repository_id") or context_data.get("repository_id")
        if not repository_id_str:
            return {
                "status": "SKIPPED",
                "message": "DevPilot step skipped: no repository_id provided in node config or workflow context.",
                "node_id": node_id,
            }

        try:
            repository_id = uuid.UUID(str(repository_id_str))
        except ValueError as err:
            raise AgentUnavailableError(
                f"Invalid repository_id format: {repository_id_str}"
            ) from err

        # Check repository exists and belongs to workspace
        repo = await db.get(Repository, repository_id)
        if not repo or repo.workspace_id != workspace_id:
            raise AgentUnavailableError(
                f"Repository {repository_id} not found in workspace {workspace_id}"
            )

        prompt = (
            config.get("prompt")
            or context_data.get("prompt")
            or "FlowForge autonomous engineering step"
        )
        title = config.get("title") or config.get("task_title") or f"FlowForge Step - {node_id}"
        task_type = config.get("task_type", "FEATURE")

        orchestrator = self.get_devpilot()
        user_id_str = context_data.get("user_id")
        user_id = uuid.UUID(str(user_id_str)) if user_id_str else None

        # Build durable dispatch identity:
        # 1. Configured explicit idempotency key in config or context
        # 2. Or workflow-level dispatch key if workflow_id is present (guarantees safe idempotent re-execution)
        # 3. Or execution-level dispatch key (execution_id:node_id:attempt_number)
        workflow_id_str = context_data.get("workflow_id")
        idempotency_key = (
            config.get("idempotency_key")
            or context_data.get("idempotency_key")
            or (f"workflow:{workflow_id_str}:{node_id}" if workflow_id_str else None)
            or (
                f"execution:{execution_id}:{node_id}:attempt_{attempt_number}"
                if execution_id
                else None
            )
        )

        from app.db.models.devpilot import DevPilotTask
        from app.db.models.flowforge import WorkflowStepExecution

        # 1. First check if a step execution already recorded a task_id for this exact execution and node
        if execution_id:
            stmt_step = (
                select(WorkflowStepExecution)
                .where(
                    WorkflowStepExecution.execution_id == execution_id,
                    WorkflowStepExecution.node_id == node_id,
                    WorkflowStepExecution.workspace_id == workspace_id,
                )
                .order_by(WorkflowStepExecution.attempt_number.desc())
                .limit(1)
            )
            prior_step = (await db.execute(stmt_step)).scalar_one_or_none()
            if (
                prior_step
                and prior_step.output_reference
                and prior_step.output_reference.get("task_id")
            ):
                task_id_val = prior_step.output_reference.get("task_id")
                try:
                    task_uuid = uuid.UUID(str(task_id_val))
                    existing_task = await db.get(DevPilotTask, task_uuid)
                    if existing_task and existing_task.workspace_id == workspace_id:
                        return {
                            "status": "COMPLETED",
                            "task_id": str(existing_task.id),
                            "task_title": existing_task.title,
                            "task_status": existing_task.status,
                            "repository_id": str(repository_id),
                            "idempotency_key": idempotency_key,
                            "reused": True,
                        }
                except (ValueError, TypeError):
                    pass

        # 2. Reconcile existing task by exact idempotency signature in prompt or metadata
        # (NEVER match purely by title, to prevent collisions with unrelated tasks sharing titles)
        if idempotency_key:
            stmt = (
                select(DevPilotTask)
                .where(
                    DevPilotTask.workspace_id == workspace_id,
                    DevPilotTask.repository_id == repository_id,
                    DevPilotTask.prompt.like(f"%[IDEMPOTENCY_KEY:{idempotency_key}]%"),
                )
                .order_by(DevPilotTask.created_at.desc())
                .limit(1)
            )
            existing_task = (await db.execute(stmt)).scalar_one_or_none()
            if existing_task:
                return {
                    "status": "COMPLETED",
                    "task_id": str(existing_task.id),
                    "task_title": existing_task.title,
                    "task_status": existing_task.status,
                    "repository_id": str(repository_id),
                    "idempotency_key": idempotency_key,
                    "reused": True,
                }

        # Embed idempotency signature into task prompt to ensure tamper-proof and stable retrieval
        full_prompt = (
            f"{prompt}\n\n[IDEMPOTENCY_KEY:{idempotency_key}]" if idempotency_key else prompt
        )

        task = await orchestrator.create_task(
            db=db,
            workspace_id=workspace_id,
            repository_id=repository_id,
            user_id=user_id,
            title=title,
            prompt=full_prompt,
            task_type=task_type,
            base_commit_sha=config.get("base_commit_sha") or context_data.get("base_commit_sha"),
        )

        return {
            "status": "COMPLETED",
            "task_id": str(task.id),
            "task_title": task.title,
            "task_status": task.status,
            "repository_id": str(repository_id),
            "idempotency_key": idempotency_key,
            "reused": False,
        }

    async def _execute_impactmind(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        node_id: str,
        config: dict[str, Any],
        context_data: dict[str, Any],
    ) -> dict[str, Any]:
        repository_id_str = config.get("repository_id") or context_data.get("repository_id")
        if not repository_id_str:
            return {
                "status": "SKIPPED",
                "message": "ImpactMind step skipped: no repository_id provided.",
                "node_id": node_id,
            }

        try:
            repository_id = uuid.UUID(str(repository_id_str))
        except ValueError as err:
            raise AgentUnavailableError(
                f"Invalid repository_id format: {repository_id_str}"
            ) from err

        repo = await db.get(Repository, repository_id)
        if not repo or repo.workspace_id != workspace_id:
            raise AgentUnavailableError(
                f"Repository {repository_id} not found in workspace {workspace_id}"
            )

        assessment = await self.get_impactmind().analyze_changes(
            db=db,
            workspace_id=workspace_id,
            repository_id=repository_id,
            diff_text=config.get("diff_text") or context_data.get("diff_text"),
            github_compare_payload=config.get("github_compare_payload"),
            base_commit_sha=config.get("base_commit_sha") or context_data.get("base_commit_sha"),
            target_commit_sha=config.get("head_commit_sha") or context_data.get("head_commit_sha"),
            user_id=uuid.UUID(str(context_data["user_id"]))
            if context_data.get("user_id")
            else None,
        )
        return {
            "status": "COMPLETED",
            "agent": "IMPACTMIND",
            "repository_id": str(repository_id),
            "assessment_id": str(assessment.id),
            "message": "ImpactMind assessment persisted.",
        }

    async def _execute_testpilot(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        node_id: str,
        config: dict[str, Any],
        context_data: dict[str, Any],
        memory_context: str,
    ) -> dict[str, Any]:
        repository_id_str = config.get("repository_id") or context_data.get("repository_id")
        if not repository_id_str:
            return {
                "status": "SKIPPED",
                "message": "TestPilot step skipped: no repository_id provided.",
                "node_id": node_id,
            }

        try:
            repository_id = uuid.UUID(str(repository_id_str))
        except ValueError as err:
            raise AgentUnavailableError(
                f"Invalid repository_id format: {repository_id_str}"
            ) from err

        repo = await db.get(Repository, repository_id)
        if not repo or repo.workspace_id != workspace_id:
            raise AgentUnavailableError(
                f"Repository {repository_id} not found in workspace {workspace_id}"
            )

        action = str(config.get("action", "GENERATE")).upper()
        target_dir = config.get("target_dir") or context_data.get("target_dir")
        if action == "DETECT":
            if not target_dir:
                return {
                    "status": "SKIPPED",
                    "agent": "TESTPILOT",
                    "repository_id": str(repository_id),
                    "message": "TestPilot detection requires target_dir.",
                }
            detection = self.get_testpilot().detect_framework(str(target_dir))
            return {
                "status": "COMPLETED",
                "agent": "TESTPILOT",
                "repository_id": str(repository_id),
                "action": action,
                "framework": detection.framework,
                "detection": detection.to_dict(),
            }

        target_files = config.get("target_files", [])
        if isinstance(target_files, str):
            target_files = [item.strip() for item in target_files.split(",") if item.strip()]
        if not isinstance(target_files, list) or not target_files:
            return {
                "status": "SKIPPED",
                "agent": "TESTPILOT",
                "repository_id": str(repository_id),
                "message": "TestPilot generation requires target_files.",
            }
        suite = await self.get_testpilot().generate_test_suite(
            db=db,
            workspace_id=workspace_id,
            repository_id=repository_id,
            framework=str(config.get("framework", "pytest")),
            target_files=target_files,
            source_context=f"{config.get('source_context', '')}\n\n{memory_context}".strip(),
            test_type=str(config.get("test_type", "UNIT")),
        )
        return {
            "status": "COMPLETED",
            "agent": "TESTPILOT",
            "repository_id": str(repository_id),
            "suite_id": str(suite.id),
            "suite_status": suite.status,
        }

    async def _execute_secureflow(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        node_id: str,
        config: dict[str, Any],
        context_data: dict[str, Any],
    ) -> dict[str, Any]:
        repository_id_str = config.get("repository_id") or context_data.get("repository_id")
        if not repository_id_str:
            return {
                "status": "SKIPPED",
                "message": "SecureFlow step skipped: no repository_id provided.",
                "node_id": node_id,
            }

        try:
            repository_id = uuid.UUID(str(repository_id_str))
        except ValueError as err:
            raise AgentUnavailableError(
                f"Invalid repository_id format: {repository_id_str}"
            ) from err

        repo = await db.get(Repository, repository_id)
        if not repo or repo.workspace_id != workspace_id:
            raise AgentUnavailableError(
                f"Repository {repository_id} not found in workspace {workspace_id}"
            )

        target_dir = config.get("target_dir") or context_data.get("target_dir")
        if not target_dir:
            return {
                "status": "SKIPPED",
                "agent": "SECUREFLOW",
                "repository_id": str(repository_id),
                "message": "SecureFlow scan requires target_dir.",
            }
        scan = await self.get_secureflow().run_scan(
            db=db,
            workspace_id=workspace_id,
            repository_id=repository_id,
            target_dir=str(target_dir),
            scan_type=str(config.get("scan_type", "FULL")),
        )
        return {
            "status": "COMPLETED",
            "agent": "SECUREFLOW",
            "repository_id": str(repository_id),
            "scan": scan.to_dict(),
        }
