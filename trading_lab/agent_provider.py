"""Provider boundary for desk agents.

The production adapter uses the OpenAI Responses API. Tests use FakeProvider.
No market order or broker capability exists in this module.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Mapping, Protocol


class ProviderError(RuntimeError):
    pass


class JsonAgentProvider(Protocol):
    def complete_json(self, *, role: str, instructions: str, prompt: str, schema_name: str, schema: Mapping[str, object]) -> Mapping[str, object]: ...


@dataclass
class OpenAIResponsesProvider:
    api_key: str | None = None
    base_url: str = "https://api.openai.com/v1"
    default_model: str = "gpt-5.6-luna"
    timeout_seconds: float = 90.0
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    def _model(self, role: str) -> str:
        key = f"TRADING_DESK_MODEL_{role.upper()}"
        return os.getenv(key, os.getenv("TRADING_DESK_MODEL", self.default_model))

    def complete_json(self, *, role: str, instructions: str, prompt: str, schema_name: str, schema: Mapping[str, object]) -> Mapping[str, object]:
        key = self.api_key or os.getenv("OPENAI_API_KEY")
        if not key:
            raise ProviderError("OPENAI_API_KEY is not configured")
        body = {
            "model": self._model(role),
            "instructions": instructions[:512],
            "input": prompt,
            "store": False,
            "text": {"format": {"type": "json_schema", "name": schema_name, "strict": True, "schema": dict(schema)}},
            "reasoning": {"effort": os.getenv("TRADING_DESK_REASONING", "low")},
            "max_output_tokens": int(os.getenv("TRADING_DESK_MAX_OUTPUT_TOKENS", "2500")),
        }
        req = urllib.request.Request(
            self.base_url.rstrip("/") + "/responses",
            data=json.dumps(body, separators=(",", ":")).encode(),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                payload = json.loads(resp.read().decode())
            self.calls += 1
            usage = payload.get("usage") if isinstance(payload, dict) else None
            if isinstance(usage, dict):
                self.input_tokens += int(usage.get("input_tokens") or 0)
                self.output_tokens += int(usage.get("output_tokens") or 0)
                self.total_tokens += int(usage.get("total_tokens") or 0)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:1000]
            raise ProviderError(f"OpenAI HTTP {exc.code}: {detail}") from exc
        except (OSError, ValueError) as exc:
            raise ProviderError(f"OpenAI request failed: {exc}") from exc
        text = payload.get("output_text")
        if not text:
            pieces = []
            for item in payload.get("output", []):
                for part in item.get("content", []) if isinstance(item, dict) else []:
                    if isinstance(part, dict) and part.get("type") == "output_text":
                        pieces.append(part.get("text", ""))
            text = "".join(pieces)
        if not isinstance(text, str) or not text.strip():
            raise ProviderError("Model returned no JSON text")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ProviderError("Model output was not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise ProviderError("Model JSON root must be an object")
        return parsed


@dataclass
class FakeProvider:
    """Deterministic provider used by tests and local plumbing checks."""
    responses: list[Mapping[str, object]]
    calls: int = 0

    def complete_json(self, **kwargs) -> Mapping[str, object]:
        if self.calls >= len(self.responses):
            raise ProviderError("No fake response left")
        out = self.responses[self.calls]
        self.calls += 1
        return dict(out)
