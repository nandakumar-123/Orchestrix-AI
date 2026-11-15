from __future__ import annotations

import json
import logging
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger("orchestrix.devpilot.llm")

# Pattern for redacting secrets from prompt and completion logs
SECRET_PATTERN = re.compile(
    r"""(?i)(?:bearer|token|secret|password|api[_-]?key|jwt)\s*[:=]\s*["']?([a-zA-Z0-9_\-\.]{8,})["']?"""
)


def redact_sensitive_text(text: str) -> str:
    """Mask tokens and secrets in logs."""
    if not text:
        return ""
    return SECRET_PATTERN.sub(r"[REDACTED_SECRET]", text)


@dataclass
class LLMCompletionResponse:
    content: str
    provider_name: str
    model_name: str
    prompt_tokens: int
    completion_tokens: int
    duration_ms: int
    is_fallback: bool = False
    raw_response: dict[str, Any] | None = None


class BaseLLMProvider(ABC):
    """Abstract base class for DevPilot LLM providers."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Name of the provider (e.g. 'gemini', 'mistral', 'mock')."""
        pass

    @property
    @abstractmethod
    def default_model(self) -> str:
        """Default model name for this provider."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Returns True if credentials are configured and valid."""
        pass

    @abstractmethod
    async def generate_completion(
        self,
        prompt: str,
        system_instruction: str | None = None,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        timeout_seconds: float = 45.0,
    ) -> LLMCompletionResponse:
        """Generate text completion from the LLM provider."""
        pass


class GeminiProvider(BaseLLMProvider):
    """Google Gemini AI provider using REST API with httpx."""

    def __init__(self, api_key: str | None = None, model: str = "gemini-3.5-flash") -> None:
        self.api_key = (api_key or settings.GEMINI_API_KEY or "").strip()
        self._model = model

    @property
    def provider_name(self) -> str:
        return "gemini"

    @property
    def default_model(self) -> str:
        return self._model

    def is_available(self) -> bool:
        return bool(self.api_key)

    async def generate_completion(
        self,
        prompt: str,
        system_instruction: str | None = None,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        timeout_seconds: float = 45.0,
    ) -> LLMCompletionResponse:
        if not self.is_available():
            raise RuntimeError("Gemini API key is not configured in settings/environment.")

        target_model = model or self._model
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{target_model}:generateContent?key={self.api_key}"
        )

        contents: list[dict[str, Any]] = []
        if system_instruction:
            contents.append({"role": "user", "parts": [{"text": f"System: {system_instruction}"}]})
            contents.append({"role": "model", "parts": [{"text": "Understood."}]})
        contents.append({"role": "user", "parts": [{"text": prompt}]})

        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }

        start_time = time.monotonic()
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code != 200:
                err_msg = redact_sensitive_text(resp.text)
                raise RuntimeError(f"Gemini API returned HTTP {resp.status_code}: {err_msg[:300]}")

            data = resp.json()
            duration_ms = int((time.monotonic() - start_time) * 1000)

            # Extract generated content
            text_out = ""
            candidates = data.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                text_out = "".join(p.get("text", "") for p in parts)

            usage = data.get("usageMetadata", {})
            p_tokens = usage.get("promptTokenCount", len(prompt) // 4)
            c_tokens = usage.get("candidatesTokenCount", len(text_out) // 4)

            return LLMCompletionResponse(
                content=text_out,
                provider_name="gemini",
                model_name=target_model,
                prompt_tokens=p_tokens,
                completion_tokens=c_tokens,
                duration_ms=duration_ms,
                raw_response={"usage": usage},
            )


class MistralProvider(BaseLLMProvider):
    """Mistral AI provider using standard Chat Completions endpoint."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ) -> None:
        self.api_key = (api_key or settings.MISTRAL_API_KEY or "").strip()
        self.base_url = (
            base_url or settings.MISTRAL_API_BASE_URL or "https://api.mistral.ai/v1"
        ).rstrip("/")
        # Prefer codestral-latest which is enabled and optimized for code generation
        configured_model = settings.MISTRAL_MODEL
        if not configured_model or configured_model == "mistral-large-latest":
            configured_model = "codestral-latest"
        self._model = model or configured_model

    @property
    def provider_name(self) -> str:
        return "mistral"

    @property
    def default_model(self) -> str:
        return self._model

    def is_available(self) -> bool:
        return bool(self.api_key)

    async def generate_completion(
        self,
        prompt: str,
        system_instruction: str | None = None,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        timeout_seconds: float = 45.0,
    ) -> LLMCompletionResponse:
        if not self.is_available():
            raise RuntimeError("Mistral API key is not configured in settings/environment.")

        target_model = model or self._model
        url = f"{self.base_url}/chat/completions"

        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        payload = {
            "model": target_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        start_time = time.monotonic()
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code != 200:
                err_msg = redact_sensitive_text(resp.text)
                raise RuntimeError(f"Mistral API returned HTTP {resp.status_code}: {err_msg[:300]}")

            data = resp.json()
            duration_ms = int((time.monotonic() - start_time) * 1000)

            choices = data.get("choices", [])
            text_out = choices[0].get("message", {}).get("content", "") if choices else ""

            usage = data.get("usage", {})
            p_tokens = usage.get("prompt_tokens", len(prompt) // 4)
            c_tokens = usage.get("completion_tokens", len(text_out) // 4)

            return LLMCompletionResponse(
                content=text_out,
                provider_name="mistral",
                model_name=target_model,
                prompt_tokens=p_tokens,
                completion_tokens=c_tokens,
                duration_ms=duration_ms,
                raw_response=data,
            )


class MockDeterministicProvider(BaseLLMProvider):
    """
    Deterministic provider for automated testing and offline development.
    Produces well-formed JSON / markdown responses according to prompt keywords.
    """

    def __init__(self, model: str = "mock-devpilot-v1") -> None:
        self._model = model

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def default_model(self) -> str:
        return self._model

    def is_available(self) -> bool:
        return True

    async def generate_completion(
        self,
        prompt: str,
        system_instruction: str | None = None,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        timeout_seconds: float = 45.0,
    ) -> LLMCompletionResponse:
        start_time = time.monotonic()
        lower_prompt = prompt.lower()

        # 1. Engineering Planning request
        if "plan" in lower_prompt or "steps" in lower_prompt:
            mock_plan = {
                "summary": "Implement requested engineering changes adhering to project conventions.",
                "task_understanding": "User requested an architectural change or enhancement.",
                "existing_implementation_analysis": "Analyzed existing repository symbols, AST declarations, and dependencies.",
                "security_implications": "Input parameters validated; secrets sanitized; no unauthorized privileges introduced.",
                "steps": [
                    {
                        "step_number": 1,
                        "title": "Update module implementation",
                        "description": "Modify the target file to implement the specified requirements.",
                        "target_files": ["src/service.py"],
                        "affected_symbols": ["process_request"],
                        "action_type": "MODIFY_FILE",
                        "reason": "Core business logic update",
                        "risk_level": "LOW",
                    },
                    {
                        "step_number": 2,
                        "title": "Add unit tests",
                        "description": "Implement regression test cases covering normal and error paths.",
                        "target_files": ["tests/test_service.py"],
                        "affected_symbols": ["test_process_request"],
                        "action_type": "ADD_TEST",
                        "reason": "Ensure test coverage and prevent regression",
                        "risk_level": "LOW",
                    },
                ],
            }
            content = json.dumps(mock_plan, indent=2)

        # 2. Code Review request
        elif "review" in lower_prompt or "findings" in lower_prompt:
            mock_review = {
                "findings": [
                    {
                        "file_path": "src/service.py",
                        "line_start": 10,
                        "line_end": 15,
                        "severity": "LOW",
                        "category": "INPUT_VALIDATION",
                        "description": "Ensure incoming payload is strictly validated before processing.",
                        "evidence": "def process_request(data): # unvalidated data access",
                        "suggested_correction": "Add Pydantic schema validation or type checks.",
                    }
                ]
            }
            content = json.dumps(mock_review, indent=2)

        # 3. Bug Diagnosis request
        elif "diagnos" in lower_prompt or "bug" in lower_prompt or "error" in lower_prompt:
            mock_diagnosis = {
                "root_cause": "Null check omission or improper error propagation in service layer.",
                "affected_files": ["src/service.py"],
                "suggested_fix": "Add boundary validation and guard clauses before accessing properties.",
            }
            content = json.dumps(mock_diagnosis, indent=2)

        # 4. Code Generation request
        else:
            mock_code = {
                "files": [
                    {
                        "file_path": "src/service.py",
                        "change_type": "MODIFY",
                        "content": "# Updated service implementation\ndef process_request(data):\n    if not data:\n        raise ValueError('Data cannot be empty')\n    return {'status': 'processed', 'data': data}\n",
                    },
                    {
                        "file_path": "tests/test_service.py",
                        "change_type": "CREATE",
                        "content": "import pytest\nfrom src.service import process_request\n\ndef test_process_request():\n    res = process_request({'key': 'val'})\n    assert res['status'] == 'processed'\n",
                    },
                ]
            }
            content = json.dumps(mock_code, indent=2)

        duration_ms = int((time.monotonic() - start_time) * 1000)
        return LLMCompletionResponse(
            content=content,
            provider_name="mock",
            model_name=model or self._model,
            prompt_tokens=len(prompt) // 4,
            completion_tokens=len(content) // 4,
            duration_ms=duration_ms,
        )


class LLMProviderManager:
    """
    Coordinates provider selection, fallback execution, and budget tracking.
    Priority order: Gemini -> Mistral -> Mock (if configured/fallback).
    """

    def __init__(
        self,
        primary_provider: str | None = None,
        force_mock: bool = False,
    ) -> None:
        self.force_mock = force_mock
        self.primary_name = primary_provider

        # Instantiate providers
        self.providers: dict[str, BaseLLMProvider] = {
            "gemini": GeminiProvider(),
            "mistral": MistralProvider(),
            "mock": MockDeterministicProvider(),
        }

    def get_provider(self, name: str) -> BaseLLMProvider | None:
        return self.providers.get(name)

    def select_active_provider(self) -> BaseLLMProvider:
        """Select the highest-priority available provider."""
        if self.force_mock:
            return self.providers["mock"]

        if self.primary_name and self.primary_name in self.providers:
            prov = self.providers[self.primary_name]
            if prov.is_available():
                return prov

        # Try Gemini first
        if self.providers["gemini"].is_available():
            return self.providers["gemini"]

        # Try Mistral second
        if self.providers["mistral"].is_available():
            return self.providers["mistral"]

        # Fallback to mock provider
        return self.providers["mock"]

    async def execute_with_fallback(
        self,
        prompt: str,
        system_instruction: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        timeout_seconds: float = 45.0,
    ) -> LLMCompletionResponse:
        """
        Execute completion with transparent, audited fallback if the primary provider fails.
        """
        if self.force_mock:
            return await self.providers["mock"].generate_completion(
                prompt=prompt,
                system_instruction=system_instruction,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout_seconds=timeout_seconds,
            )

        active = self.select_active_provider()
        errors: list[str] = []

        # 1. Try active provider
        try:
            return await active.generate_completion(
                prompt=prompt,
                system_instruction=system_instruction,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout_seconds=timeout_seconds,
            )
        except Exception as e:
            err_msg = f"{active.provider_name} failed: {e}"
            logger.warning(err_msg)
            errors.append(err_msg)

        # 2. Try alternative configured provider if active wasn't mock
        for prov_name, prov in self.providers.items():
            if prov_name != active.provider_name and prov_name != "mock" and prov.is_available():
                try:
                    logger.info(f"Falling back to {prov_name}...")
                    res = await prov.generate_completion(
                        prompt=prompt,
                        system_instruction=system_instruction,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        timeout_seconds=timeout_seconds,
                    )
                    res.is_fallback = True
                    return res
                except Exception as e:
                    err_fallback = f"Fallback {prov_name} failed: {e}"
                    logger.warning(err_fallback)
                    errors.append(err_fallback)

        # 3. If live providers failed, fallback to mock provider with notification
        logger.warning(f"All live providers failed ({errors}); using deterministic fallback.")
        mock_res = await self.providers["mock"].generate_completion(
            prompt=prompt,
            system_instruction=system_instruction,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
        )
        mock_res.is_fallback = True
        return mock_res
