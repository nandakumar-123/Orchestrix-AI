from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utc_now
from app.db.models.devpilot import DevPilotEvent, DevPilotTask, EngineeringPlan, EngineeringPlanStep
from app.services.devpilot.context_builder import DevPilotContext
from app.services.devpilot.llm_provider import LLMProviderManager
from app.services.impactmind.engine import ImpactMindEngine

logger = logging.getLogger("orchestrix.devpilot.planner")


PLANNER_SYSTEM_PROMPT = """You are DevPilot, an expert repository-aware software engineering planner for Orchestrix AI.
Given a user's engineering task request and the retrieved repository context (symbols, AST declarations, dependencies),
generate a comprehensive, structured implementation plan before any code is generated or modified.

You must respond with valid JSON adhering strictly to this schema:
{
  "summary": "Short 1-2 sentence executive summary of the plan",
  "task_understanding": "Detailed explanation of what needs to be accomplished and why",
  "existing_implementation_analysis": "Summary of current repository code, architecture, and relevant files",
  "security_implications": "Security analysis (input validation, authorization, secrets, edge cases)",
  "steps": [
    {
      "step_number": 1,
      "title": "Concise step title",
      "description": "Specific action to perform",
      "target_files": ["path/to/file.py"],
      "affected_symbols": ["function_or_class_name"],
      "action_type": "CREATE_FILE | MODIFY_FILE | DELETE_FILE | REFACTOR_SYMBOL | ADD_TEST | RUN_MIGRATION",
      "reason": "Why this step is needed",
      "risk_level": "LOW | MEDIUM | HIGH | CRITICAL"
    }
  ]
}
"""


class EngineeringPlanningEngine:
    """
    Synthesizes structured implementation plans for DevPilot engineering tasks.
    Integrates LLM provider generation, ImpactMind baseline exposure analysis,
    and PostgreSQL persistence. Enforces human approval before code modification.
    """

    def __init__(
        self,
        llm_manager: LLMProviderManager | None = None,
        impact_engine: ImpactMindEngine | None = None,
    ) -> None:
        self.llm_manager = llm_manager or LLMProviderManager()
        self.impact_engine = impact_engine or ImpactMindEngine()

    async def generate_plan(
        self,
        db: AsyncSession,
        task: DevPilotTask,
        context: DevPilotContext,
    ) -> EngineeringPlan:
        """
        Draft a 14-section engineering plan and record steps in database.
        """
        # If task was determined ambiguous or dangerous, stop and request clarification
        if context.is_ambiguous or context.is_dangerous:
            task.status = "NEEDS_CLARIFICATION"
            task.clarification_prompt = context.clarification_prompt
            db.add(
                DevPilotEvent(
                    task_id=task.id,
                    workspace_id=task.workspace_id,
                    event_type="CLARIFICATION_REQUIRED",
                    message=context.clarification_prompt
                    or "Task needs clarification before planning.",
                )
            )
            await db.commit()
            raise ValueError(context.clarification_prompt or "Task requires user clarification.")

        task.status = "PLANNING"
        db.add(
            DevPilotEvent(
                task_id=task.id,
                workspace_id=task.workspace_id,
                event_type="PLANNING_STARTED",
                message=f"DevPilot is formulating implementation plan for: {task.title}",
            )
        )
        await db.commit()

        # Build prompt for LLM
        prompt = (
            f"Task Title: {task.title}\n"
            f"Task Type: {task.task_type}\n"
            f"Task Prompt: {task.prompt}\n\n"
            f"{context.context_markdown}\n\n"
            f"Output the JSON implementation plan now:"
        )

        llm_response = await self.llm_manager.execute_with_fallback(
            prompt=prompt,
            system_instruction=PLANNER_SYSTEM_PROMPT,
            temperature=0.2,
        )

        # Parse LLM JSON output with fallback handling
        plan_data: dict[str, Any] = {}
        try:
            # Strip markdown code fences if LLM wrapped JSON in ```json ... ```
            raw_text = llm_response.content.strip()
            if raw_text.startswith("```"):
                lines = raw_text.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                raw_text = "\n".join(lines).strip()
            plan_data = json.loads(raw_text)
        except Exception as e:
            logger.warning(
                f"Failed to parse LLM planning JSON: {e}; using structured fallback plan."
            )
            plan_data = {
                "summary": f"Plan for {task.title}",
                "task_understanding": task.prompt,
                "existing_implementation_analysis": f"Repository has {len(context.relevant_files)} relevant files.",
                "security_implications": "All inputs must be sanitized; privileges validated.",
                "steps": [
                    {
                        "step_number": 1,
                        "title": f"Implement {task.title}",
                        "description": "Modify designated module to satisfy task requirements.",
                        "target_files": context.relevant_files[:2] or ["src/main.py"],
                        "affected_symbols": [s["name"] for s in context.relevant_symbols[:2]],
                        "action_type": "MODIFY_FILE",
                        "reason": "Fulfill user request",
                        "risk_level": "LOW",
                    },
                    {
                        "step_number": 2,
                        "title": "Add regression tests",
                        "description": "Ensure new functionality is covered by automated tests.",
                        "target_files": context.existing_tests[:1] or ["tests/test_feature.py"],
                        "affected_symbols": ["test_feature"],
                        "action_type": "ADD_TEST",
                        "reason": "Prevent regressions",
                        "risk_level": "LOW",
                    },
                ],
            }

        # Baseline ImpactMind Assessment
        exposure_score = 0.0
        exposure_tier = "LOW"
        impact_id = None
        try:
            # Synthetic diff based on planned files to evaluate baseline exposure
            planned_files = []
            for st in plan_data.get("steps", []):
                planned_files.extend(st.get("target_files", []))
            planned_files = list(set(planned_files))

            if planned_files:
                synthetic_diff = "\n".join(
                    f"diff --git a/{f} b/{f}\n--- a/{f}\n+++ b/{f}\n@@ -1,3 +1,4 @@\n+# Planned change by DevPilot\n"
                    for f in planned_files[:5]
                )
                assessment = await self.impact_engine.analyze_changes(
                    db=db,
                    workspace_id=task.workspace_id,
                    repository_id=task.repository_id,
                    diff_text=synthetic_diff,
                    snapshot_id=task.snapshot_id,
                    comparison_mode="diff_input",
                )
                exposure_score = assessment.structural_exposure_score
                exposure_tier = assessment.exposure_tier
                impact_id = assessment.id
        except Exception as e:
            logger.warning(f"ImpactMind baseline assessment skipped or failed: {e}")

        # Persist EngineeringPlan
        plan = EngineeringPlan(
            task_id=task.id,
            workspace_id=task.workspace_id,
            summary=plan_data.get("summary", f"Implementation plan for {task.title}"),
            task_understanding=plan_data.get("task_understanding", task.prompt),
            existing_implementation_analysis=plan_data.get(
                "existing_implementation_analysis", "Analyzed target codebase."
            ),
            security_implications=plan_data.get(
                "security_implications", "Standard input validation enforced."
            ),
            impact_assessment_id=impact_id,
            exposure_score=exposure_score,
            exposure_tier=exposure_tier,
            status="PENDING",
            created_at=utc_now(),
        )
        db.add(plan)
        await db.flush()

        # Persist Steps
        for s_idx, st in enumerate(plan_data.get("steps", []), start=1):
            step = EngineeringPlanStep(
                plan_id=plan.id,
                step_number=st.get("step_number", s_idx),
                title=st.get("title", f"Step {s_idx}"),
                description=st.get("description", ""),
                target_files=st.get("target_files", []),
                affected_symbols=st.get("affected_symbols", []),
                action_type=st.get("action_type", "MODIFY_FILE"),
                reason=st.get("reason", "Required modification"),
                risk_level=st.get("risk_level", "LOW"),
                status="PLANNED",
            )
            db.add(step)

        # Transition Task to AWAITING_APPROVAL
        task.status = "AWAITING_APPROVAL"
        db.add(
            DevPilotEvent(
                task_id=task.id,
                workspace_id=task.workspace_id,
                event_type="PLAN_GENERATED",
                message=f"Plan generated with {len(plan_data.get('steps', []))} steps. Awaiting human approval.",
                details={
                    "plan_id": str(plan.id),
                    "exposure_score": exposure_score,
                    "exposure_tier": exposure_tier,
                    "provider_used": llm_response.provider_name,
                    "model_used": llm_response.model_name,
                },
            )
        )
        await db.commit()
        await db.refresh(plan)
        return plan
