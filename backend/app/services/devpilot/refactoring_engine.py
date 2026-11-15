from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from app.services.devpilot.context_builder import DevPilotContext
from app.services.devpilot.llm_provider import LLMProviderManager

logger = logging.getLogger("orchestrix.devpilot.refactoring")


@dataclass
class RefactoringCandidate:
    target_file: str
    target_symbol: str
    refactoring_type: str  # EXTRACT_FUNCTION, DEDUPLICATE, IMPROVE_TYPING, MODULARIZE
    reason: str
    preserves_public_api: bool


class RefactoringEngine:
    """
    Analyzes code structures for refactoring opportunities:
    Function extraction, duplicate reduction, typing enhancements, and modularization.
    """

    def __init__(self, llm_manager: LLMProviderManager | None = None) -> None:
        self.llm_manager = llm_manager or LLMProviderManager()

    async def analyze_refactoring_scope(
        self,
        refactoring_goal: str,
        context: DevPilotContext,
    ) -> list[RefactoringCandidate]:
        """Formulate safe, non-breaking refactoring candidates."""
        prompt = (
            f"# Refactoring Goal: {refactoring_goal}\n\n"
            f"## Repository Context:\n{context.context_markdown}\n\n"
            f"Analyze the code and output a list of refactoring candidates adhering to this JSON schema:\n"
            f'{{"candidates": [{{"target_file": "...", "target_symbol": "...", "refactoring_type": "...", "reason": "...", "preserves_public_api": true}}]}}'
        )

        llm_res = await self.llm_manager.execute_with_fallback(
            prompt=prompt,
            system_instruction="You are DevPilot Refactoring Engine. Prioritize backward compatibility and type safety.",
            temperature=0.1,
        )

        candidates: list[RefactoringCandidate] = []
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
            for c in data.get("candidates", []):
                candidates.append(
                    RefactoringCandidate(
                        target_file=c.get(
                            "target_file",
                            context.relevant_files[0] if context.relevant_files else "",
                        ),
                        target_symbol=c.get("target_symbol", ""),
                        refactoring_type=c.get("refactoring_type", "EXTRACT_FUNCTION"),
                        reason=c.get("reason", "Code simplification"),
                        preserves_public_api=bool(c.get("preserves_public_api", True)),
                    )
                )
        except Exception as e:
            logger.warning(f"Failed to parse refactoring JSON: {e}")
            if context.relevant_symbols:
                candidates.append(
                    RefactoringCandidate(
                        target_file=context.relevant_symbols[0]["file_path"],
                        target_symbol=context.relevant_symbols[0]["name"],
                        refactoring_type="IMPROVE_TYPING",
                        reason="Enhance type annotations and error guards",
                        preserves_public_api=True,
                    )
                )
        return candidates
