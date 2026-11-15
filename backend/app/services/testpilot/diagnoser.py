from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.services.devpilot.llm_provider import LLMProviderManager, redact_sensitive_text
from app.services.secureflow.redaction import redact_secrets
from app.services.testpilot.schemas import DiagnosisReport

logger = logging.getLogger("orchestrix.testpilot.diagnoser")

TRACEBACK_FILE_LINE_PATTERN = re.compile(
    r"""File\s+["']([^"']+)["'],\s+line\s+(\d+)(?:,\s+in\s+([\w_]+))?""", re.MULTILINE
)
JS_STACK_LINE_PATTERN = re.compile(r"""at\s+(?:([\w\.<>]+)\s+\()?([^:()]+):(\d+):(\d+)\)?""")


class FailureDiagnoser:
    """
    Test Failure Diagnosis Engine.
    Parses test failure logs, stack traces, and relevant AST context.
    Executes pre-LLM secret scrubbing to ensure zero credential leakage.
    Produces actionable root-cause explanations and fix suggestions.
    Never automatically applies fixes or modifies source repositories.
    """

    def __init__(self, llm_manager: LLMProviderManager | None = None) -> None:
        self.llm_manager = llm_manager or LLMProviderManager()

    def parse_traceback(self, raw_traceback: str) -> dict[str, Any]:
        """Parse structured frames from raw Python or JavaScript stack traces."""
        frames: list[dict[str, Any]] = []
        error_type: str | None = None
        error_msg: str | None = None

        clean_tb = raw_traceback.strip()

        # Python traceback parsing
        py_matches = list(TRACEBACK_FILE_LINE_PATTERN.finditer(clean_tb))
        if py_matches:
            for m in py_matches:
                frames.append(
                    {
                        "file": m.group(1).replace("\\", "/"),
                        "line": int(m.group(2)),
                        "function": m.group(3) or "module",
                    }
                )
            # Find trailing error line (e.g. "AssertionError: expected 200 got 500")
            lines = clean_tb.splitlines()
            for line in reversed(lines):
                line_str = line.strip()
                if line_str and not line_str.startswith("File "):
                    if ":" in line_str:
                        parts = line_str.split(":", 1)
                        error_type = parts[0].strip()
                        error_msg = parts[1].strip()
                    else:
                        error_msg = line_str
                    break

        # JavaScript stack trace parsing
        if not frames:
            js_matches = list(JS_STACK_LINE_PATTERN.finditer(clean_tb))
            for m in js_matches:
                frames.append(
                    {
                        "function": m.group(1) or "anonymous",
                        "file": m.group(2).replace("\\", "/"),
                        "line": int(m.group(3)),
                        "col": int(m.group(4)),
                    }
                )
            first_line = clean_tb.splitlines()[0] if clean_tb else ""
            if ":" in first_line:
                parts = first_line.split(":", 1)
                error_type = parts[0].strip()
                error_msg = parts[1].strip()

        return {
            "error_type": error_type or "TestFailure",
            "error_message": error_msg or "Test failed during execution",
            "frames": frames,
            "last_frame": frames[-1] if frames else None,
        }

    async def diagnose(
        self,
        failing_test_name: str,
        stdout: str,
        stderr: str,
        source_context: str | None = None,
        target_symbol: str | None = None,
    ) -> DiagnosisReport:
        """
        Diagnose a failed test run, identifying root causes and suggested remedies.
        Strictly redacts sensitive environment variables and tokens before external LLM calls.
        """
        raw_error_text = f"{stdout}\n{stderr}"
        parsed_tb = self.parse_traceback(raw_error_text)

        # Mandatory Pre-LLM Secret Redaction
        clean_tb_text = redact_secrets(redact_sensitive_text(raw_error_text))
        clean_context = redact_secrets(redact_sensitive_text(source_context or ""))

        affected_files: list[str] = []
        if parsed_tb.get("frames"):
            affected_files = list(
                {
                    f["file"]
                    for f in parsed_tb["frames"]
                    if not f["file"].startswith(("<", "node_modules"))
                }
            )

        system_instruction = (
            "You are TestPilot Failure Diagnoser. Analyze the provided test failure traceback and source code. "
            "Explain the exact root cause of the test failure and propose 2-4 concrete, idiomatic code fixes. "
            "Do NOT modify the source repository. Output ONLY a valid JSON object."
        )

        prompt = f"""Failing Test: {failing_test_name}
Target Symbol: {target_symbol or "Unknown"}
Error Summary: {parsed_tb.get("error_type")}: {parsed_tb.get("error_message")}

Sanitized Traceback:
```
{clean_tb_text[-4000:]}
```

Relevant Source Code:
```
{clean_context[:8000]}
```

Provide JSON output:
{{
  "root_cause": "Precise explanation of why the test failed",
  "suggestions": [
    "Fix suggestion 1",
    "Fix suggestion 2"
  ],
  "confidence": 0.90
}}
"""

        try:
            resp = await self.llm_manager.execute_with_fallback(
                prompt=prompt,
                system_instruction=system_instruction,
                temperature=0.1,
                max_tokens=2048,
            )
            raw_content = resp.content.strip()
            if raw_content.startswith("```"):
                raw_content = re.sub(r"^```(?:json)?\s*", "", raw_content)
                raw_content = re.sub(r"\s*```$", "", raw_content)

            parsed = json.loads(raw_content)
            root_cause = parsed.get("root_cause", "Assertion mismatch detected in test execution.")
            suggestions = parsed.get("suggestions", ["Review function contract and assertions."])
            confidence = float(parsed.get("confidence", 0.85))
        except Exception as e:
            logger.warning(f"Diagnosis LLM analysis failed: {e}. Generating rule-based diagnosis.")
            root_cause = f"Failure occurred with {parsed_tb.get('error_type')}: {parsed_tb.get('error_message')}"
            suggestions = [
                f"Verify inputs passed to {target_symbol or failing_test_name}",
                "Inspect boundary condition handling in caller frame",
            ]
            confidence = 0.70

        return DiagnosisReport(
            failing_test=failing_test_name,
            error_message=f"{parsed_tb.get('error_type')}: {parsed_tb.get('error_message')}",
            traceback_parsed=parsed_tb,
            root_cause_analysis=root_cause,
            fix_suggestions=suggestions,
            affected_files=affected_files,
            confidence=confidence,
            target_symbol=target_symbol,
        )
