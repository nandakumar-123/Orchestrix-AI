from __future__ import annotations

import json
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utc_now
from app.db.models.devpilot import (
    CodeGenerationResult,
    CodeReviewFinding,
    DevPilotEvent,
    DevPilotTask,
    EngineeringPlan,
)
from app.services.devpilot.llm_provider import LLMProviderManager

logger = logging.getLogger("orchestrix.devpilot.code_reviewer")

REVIEWER_SYSTEM_PROMPT = """You are DevPilot Code Reviewer for Orchestrix AI.
Thoroughly review proposed code changes against the approved plan across these 10 quality dimensions:
1. Correctness & logic errors
2. Security vulnerabilities (injection, auth, sensitive data)
3. Input validation & sanitization
4. Error handling & exception propagation
5. Type safety & null checks
6. Code duplication
7. Performance & algorithmic complexity
8. Architectural consistency with existing codebase
9. Dependency changes
10. Test coverage & edge cases

Respond ONLY with valid JSON following this schema:
{
  "findings": [
    {
      "file_path": "path/to/file.ext",
      "line_start": 1,
      "line_end": 5,
      "severity": "INFO | LOW | MEDIUM | HIGH | CRITICAL",
      "category": "CORRECTNESS | SECURITY | INPUT_VALIDATION | ERROR_HANDLING | TYPE_SAFETY | PERFORMANCE | ARCHITECTURE | DUPLICATION",
      "description": "Clear explanation of the finding",
      "evidence": "Code snippet or context showing the issue",
      "suggested_correction": "Specific recommendation or fix"
    }
  ]
}
"""


class CodeReviewEngine:
    """
    Automated code review engine analyzing proposed diffs and generated files.
    Enforces plan scope containment, security rules, and code quality.
    """

    def __init__(self, llm_manager: LLMProviderManager | None = None) -> None:
        self.llm_manager = llm_manager or LLMProviderManager()

    async def review_changes(
        self,
        db: AsyncSession,
        task: DevPilotTask,
        plan: EngineeringPlan,
        generation_result: CodeGenerationResult,
    ) -> list[CodeReviewFinding]:
        """
        Perform automated code review of generated modifications.
        """
        findings: list[CodeReviewFinding] = []

        # 1. Scope Containment Check: Compare generated files against planned target files
        planned_targets: set[str] = set()
        for s in plan.steps:
            for tf in s.target_files:
                planned_targets.add(tf.replace("\\", "/"))

        for change in generation_result.changes:
            norm_path = change.file_path.replace("\\", "/")
            if norm_path not in planned_targets:
                findings.append(
                    CodeReviewFinding(
                        task_id=task.id,
                        workspace_id=task.workspace_id,
                        file_path=change.file_path,
                        line_start=1,
                        line_end=1,
                        severity="HIGH",
                        category="ARCHITECTURE",
                        description=f"Scope violation: '{change.file_path}' was modified but was not included in the approved implementation plan.",
                        evidence=change.diff_hunk[:200] if change.diff_hunk else None,
                        suggested_correction="Revert changes to this file or seek approval for expanding task scope.",
                        created_at=utc_now(),
                    )
                )

        # 2. LLM Review of Unified Diff
        if generation_result.unified_diff.strip():
            prompt = (
                f"# Task: {task.title}\n"
                f"# Plan Summary: {plan.summary}\n\n"
                f"## Unified Diff of Proposed Changes:\n"
                f"```diff\n{generation_result.unified_diff[:16000]}\n```\n\n"
                f"Review the diff thoroughly and output JSON findings now:"
            )

            try:
                llm_res = await self.llm_manager.execute_with_fallback(
                    prompt=prompt,
                    system_instruction=REVIEWER_SYSTEM_PROMPT,
                    temperature=0.1,
                )
                raw_text = llm_res.content.strip()
                if raw_text.startswith("```"):
                    lines = raw_text.splitlines()
                    if lines[0].startswith("```"):
                        lines = lines[1:]
                    if lines and lines[-1].startswith("```"):
                        lines = lines[:-1]
                    raw_text = "\n".join(lines).strip()
                parsed = json.loads(raw_text)
                for f_data in parsed.get("findings", []):
                    findings.append(
                        CodeReviewFinding(
                            task_id=task.id,
                            workspace_id=task.workspace_id,
                            file_path=f_data.get("file_path", "unknown"),
                            line_start=f_data.get("line_start"),
                            line_end=f_data.get("line_end"),
                            severity=f_data.get("severity", "LOW").upper(),
                            category=f_data.get("category", "CORRECTNESS").upper(),
                            description=f_data.get("description", "Code review observation"),
                            evidence=f_data.get("evidence"),
                            suggested_correction=f_data.get("suggested_correction"),
                            created_at=utc_now(),
                        )
                    )
            except Exception as e:
                logger.warning(f"LLM code review parse error: {e}")

        # Persist findings
        for f in findings:
            db.add(f)

        # Transition task to AWAITING_MODIFICATION_APPROVAL
        task.status = "AWAITING_MODIFICATION_APPROVAL"
        db.add(
            DevPilotEvent(
                task_id=task.id,
                workspace_id=task.workspace_id,
                event_type="REVIEW_COMPLETED",
                message=f"Code review completed with {len(findings)} findings. Awaiting modification approval.",
                details={
                    "total_findings": len(findings),
                    "severities": {
                        "critical": sum(1 for f in findings if f.severity == "CRITICAL"),
                        "high": sum(1 for f in findings if f.severity == "HIGH"),
                        "medium": sum(1 for f in findings if f.severity == "MEDIUM"),
                        "low": sum(1 for f in findings if f.severity == "LOW"),
                    },
                },
            )
        )
        await db.commit()
        return findings
