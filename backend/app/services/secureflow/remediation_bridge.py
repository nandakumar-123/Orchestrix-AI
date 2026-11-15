from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utc_now
from app.db.models.devpilot import DevPilotTask
from app.db.models.secureflow import SecureFlowFinding
from app.services.secureflow.exceptions import SecureFlowError
from app.services.secureflow.redaction import redact_secrets
from app.services.secureflow.schemas import RemediationTaskResult

if TYPE_CHECKING:
    from app.services.devpilot.orchestrator import DevPilotOrchestrator

logger = logging.getLogger("orchestrix.secureflow.remediation_bridge")


class DevPilotRemediationBridge:
    """
    Internal remediation bridge connecting SecureFlow to DevPilot.
    Converts security vulnerabilities into structured DevPilot remediation tasks.
    Enforces secret scrubbing before task creation and preserves strict human approval boundaries.
    Never automatically modifies code, commits, or pushes fixes.
    """

    def __init__(self, devpilot_orchestrator: DevPilotOrchestrator | None = None) -> None:
        if devpilot_orchestrator is None:
            from app.services.devpilot.orchestrator import DevPilotOrchestrator

            self.devpilot_orchestrator = DevPilotOrchestrator()
        else:
            self.devpilot_orchestrator = devpilot_orchestrator

    async def create_remediation_task(
        self,
        db: AsyncSession,
        finding_id: uuid.UUID,
        user_id: uuid.UUID | None = None,
    ) -> RemediationTaskResult:
        """
        Convert a SecureFlowFinding into a structured DevPilot remediation task.
        """
        finding = await db.get(SecureFlowFinding, finding_id)
        if not finding:
            raise SecureFlowError(f"Security finding {finding_id} not found")

        # Check if remediation task was already linked
        if finding.devpilot_task_id:
            existing_task = await db.get(DevPilotTask, finding.devpilot_task_id)
            if existing_task:
                return RemediationTaskResult(
                    finding_id=finding.id,
                    devpilot_task_id=existing_task.id,
                    task_title=existing_task.title,
                    task_status=existing_task.status,
                    requires_plan_approval=True,
                    requires_code_approval=True,
                )

        # 1. Prepare sanitized remediation prompt
        clean_title = redact_secrets(finding.title)
        clean_desc = redact_secrets(finding.description)
        clean_rec = redact_secrets(finding.remediation_recommendation or "")

        remediation_prompt = (
            f"Remediate {finding.severity} security vulnerability ({finding.rule_id}): {clean_title}\n\n"
            f"Category: {finding.category}\n"
            f"File: {finding.file_path or 'manifest'}\n"
            f"Lines: {finding.line_start or 0} - {finding.line_end or 0}\n\n"
            f"Description:\n{clean_desc}\n\n"
            f"Recommended Remediation:\n{clean_rec}\n\n"
            "Requirements:\n"
            "1. Fix the vulnerability following security best practices.\n"
            "2. Ensure backwards compatibility and prevent regressions.\n"
            "3. Do not alter any credentials or secrets.\n"
        )

        task_title = f"Security Remediation: {clean_title[:80]}"

        # 2. Call DevPilot Orchestrator to create the task
        task = await self.devpilot_orchestrator.create_task(
            db=db,
            workspace_id=finding.workspace_id,
            repository_id=finding.repository_id,
            user_id=user_id,
            title=task_title,
            prompt=remediation_prompt,
            task_type="SECURITY",
        )

        # 3. Link task ID to the finding
        finding.devpilot_task_id = task.id
        finding.updated_at = utc_now()
        await db.commit()

        return RemediationTaskResult(
            finding_id=finding.id,
            devpilot_task_id=task.id,
            task_title=task.title,
            task_status=task.status,
            requires_plan_approval=True,
            requires_code_approval=True,
        )
