from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from app.services.devpilot.context_builder import DevPilotContext
from app.services.devpilot.llm_provider import LLMProviderManager

logger = logging.getLogger("orchestrix.devpilot.bug_diagnoser")

STACK_TRACE_FILE_PATTERN = re.compile(r'File "([^"]+)", line (\d+), in (\w+)')


@dataclass
class BugDiagnosisResult:
    root_cause: str
    affected_files: list[str]
    affected_symbols: list[str]
    suggested_fix: str
    evidence: str | None = None


class BugDiagnosisEngine:
    """
    Diagnoses bugs from natural language reports, stack traces, and test output.
    Identifies failing source lines and formulates targeted fixes.
    """

    def __init__(self, llm_manager: LLMProviderManager | None = None) -> None:
        self.llm_manager = llm_manager or LLMProviderManager()

    def parse_stack_trace_frames(self, error_text: str) -> list[dict[str, Any]]:
        """Extract referenced files, lines, and functions from traceback logs."""
        frames: list[dict[str, Any]] = []
        for match in STACK_TRACE_FILE_PATTERN.finditer(error_text):
            f_path, line_no, func_name = match.groups()
            frames.append(
                {
                    "file_path": f_path.replace("\\", "/"),
                    "line": int(line_no),
                    "function": func_name,
                }
            )
        return frames

    async def diagnose_issue(
        self,
        bug_report: str,
        context: DevPilotContext,
        error_logs: str | None = None,
    ) -> BugDiagnosisResult:
        """Analyze reported defect and suggest precise fix."""
        frames = self.parse_stack_trace_frames(error_logs or "")
        frame_summary = "\n".join(
            f"- File: `{fr['file_path']}` line {fr['line']} in `{fr['function']}`" for fr in frames
        )

        prompt = (
            f"# Bug Report: {bug_report}\n\n"
            f"## Stack Trace / Error Logs:\n{error_logs or 'None provided'}\n\n"
            f"## Parsed Stack Frames:\n{frame_summary or 'None'}\n\n"
            f"## Repository Context:\n{context.context_markdown}\n\n"
            f"Diagnose the root cause and provide structured output JSON with:\n"
            f'{{"root_cause": "...", "affected_files": ["..."], "affected_symbols": ["..."], "suggested_fix": "..."}}'
        )

        llm_res = await self.llm_manager.execute_with_fallback(
            prompt=prompt,
            system_instruction="You are DevPilot Bug Diagnosis Engine. Output clean JSON only.",
            temperature=0.1,
        )

        try:
            raw = llm_res.content.strip()
            if raw.startswith("```"):
                lines = raw.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                raw = "\n".join(lines).strip()
            data = json.loads(raw)
            return BugDiagnosisResult(
                root_cause=data.get("root_cause", "Unspecified bug pattern"),
                affected_files=data.get("affected_files", context.relevant_files[:2]),
                affected_symbols=data.get(
                    "affected_symbols", [s["name"] for s in context.relevant_symbols[:2]]
                ),
                suggested_fix=data.get(
                    "suggested_fix", "Apply defensive validation and boundary checks."
                ),
                evidence=frame_summary or error_logs,
            )
        except Exception as e:
            logger.warning(f"Failed to parse bug diagnosis JSON: {e}")
            return BugDiagnosisResult(
                root_cause="Defect detected from error output or user report.",
                affected_files=context.relevant_files[:2],
                affected_symbols=[s["name"] for s in context.relevant_symbols[:2]],
                suggested_fix="Inspect error frames and add null-checks/exception guards.",
                evidence=error_logs,
            )
