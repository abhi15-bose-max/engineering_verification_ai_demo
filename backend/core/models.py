"""Model-agnostic adapter layer.

The rest of the platform never imports openai/google-genai directly - it
only talks to ModelAdapter.generate(prompt). This is what "bring your model"
means architecturally: adding a new provider means writing one adapter, not
touching the orchestrator or any domain.
"""
from __future__ import annotations

import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass


class ModelError(Exception):
    """Raised when a model call fails (network, auth, malformed response)."""


@dataclass
class GenerationResult:
    text: str
    latency_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None


class ModelAdapter(ABC):
    id: str
    display_name: str

    @abstractmethod
    def available(self) -> bool:
        """Whether this adapter is usable right now (e.g. API key present)."""

    @abstractmethod
    def _call(self, prompt: str, max_tokens: int) -> tuple[str, int | None, int | None]:
        """Provider-specific call. Returns (text, input_tokens, output_tokens)."""

    def generate(self, prompt: str, max_tokens: int = 1400) -> GenerationResult:
        if not self.available():
            raise ModelError(f"{self.display_name} is not configured (missing API key).")
        started = time.perf_counter()
        try:
            text, in_tok, out_tok = self._call(prompt, max_tokens)
        except ModelError:
            raise
        except Exception as exc:  # noqa: BLE001 - surface any SDK error uniformly
            raise ModelError(f"{self.display_name} request failed: {exc}") from exc
        latency_ms = int((time.perf_counter() - started) * 1000)
        if not text or not text.strip():
            raise ModelError(f"{self.display_name} returned an empty response.")
        return GenerationResult(text=text.strip(), latency_ms=latency_ms,
                                 input_tokens=in_tok, output_tokens=out_tok)


class OpenAIAdapter(ModelAdapter):
    id = "gpt"
    display_name = "GPT"

    def __init__(self, model_name: str | None = None):
        self.model_name = model_name or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self._client = None

    def available(self) -> bool:
        return bool(os.getenv("OPENAI_API_KEY"))

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        return self._client

    def _call(self, prompt: str, max_tokens: int):
        client = self._get_client()
        response = client.chat.completions.create(
            model=self.model_name,
            messages=[
                {"role": "system", "content": "You are a precise engineering AI. Follow output format instructions exactly."},
                {"role": "user", "content": prompt},
            ],
            max_completion_tokens=max_tokens,
        )
        text = response.choices[0].message.content or ""
        usage = getattr(response, "usage", None)
        in_tok = getattr(usage, "prompt_tokens", None) if usage else None
        out_tok = getattr(usage, "completion_tokens", None) if usage else None
        return text, in_tok, out_tok


class GeminiAdapter(ModelAdapter):
    id = "gemini"
    display_name = "Gemini"

    def __init__(self, model_name: str | None = None):
        self.model_name = model_name or os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        self._client = None

    def available(self) -> bool:
        return bool(os.getenv("GEMINI_API_KEY"))

    def _get_client(self):
        if self._client is None:
            from google import genai
            self._client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        return self._client

    def _call(self, prompt: str, max_tokens: int):
        client = self._get_client()
        from google.genai import types
        response = client.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config=types.GenerateContentConfig(max_output_tokens=max_tokens),
        )
        text = response.text or ""
        usage = getattr(response, "usage_metadata", None)
        in_tok = getattr(usage, "prompt_token_count", None) if usage else None
        out_tok = getattr(usage, "candidates_token_count", None) if usage else None
        return text, in_tok, out_tok


class MockAdapter(ModelAdapter):
    """Deterministic offline adapter used by tests and when no keys are set."""

    id = "mock"
    display_name = "Mock"

    def __init__(self, script: list[str] | None = None):
        self._script = list(script or [])
        self._i = 0

    def available(self) -> bool:
        return True

    def _call(self, prompt: str, max_tokens: int):
        if self._script:
            text = self._script[min(self._i, len(self._script) - 1)]
            self._i += 1
        else:
            text = ""
        return text, None, None


_REGISTRY: dict[str, ModelAdapter] = {}


def get_model_adapters() -> dict[str, ModelAdapter]:
    """Returns id -> adapter for every model the platform knows about."""
    if not _REGISTRY:
        _REGISTRY["gpt"] = OpenAIAdapter()
        _REGISTRY["gemini"] = GeminiAdapter()
    return _REGISTRY


def get_available_models() -> list[dict]:
    return [
        {"id": a.id, "name": a.display_name, "available": a.available()}
        for a in get_model_adapters().values()
    ]


def get_model(model_id: str) -> ModelAdapter:
    adapters = get_model_adapters()
    if model_id not in adapters:
        raise ModelError(f"Unknown model '{model_id}'.")
    return adapters[model_id]
