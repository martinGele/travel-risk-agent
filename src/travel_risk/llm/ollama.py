"""Self-hosted model via Ollama (default: Qwen 2.5 7B). No data leaves the machine."""

from __future__ import annotations

import json
import time

import httpx
from pydantic import ValidationError

from travel_risk.llm.base import AssessmentInput, ModelError, ModelResult
from travel_risk.llm.prompt import OUTPUT_SCHEMA, PROMPT_VERSION, SYSTEM_PROMPT, build_user_message
from travel_risk.schemas import RiskAssessment

DEFAULT_MODEL = "qwen2.5:7b"
# Ollama's default context is a few thousand tokens and it silently drops the start of longer
# prompts. Long FCDO pages need more, so set it explicitly and check the count afterwards.
NUM_CTX = 16384


class OllamaRiskModel:
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        base_url: str = "http://localhost:11434",
        http: httpx.Client | None = None,
        timeout: float = 300.0,
    ) -> None:
        self.name = f"ollama/{model}"
        self.model = model
        self.http = http or httpx.Client(base_url=base_url, timeout=timeout)

    def assess(self, item: AssessmentInput) -> ModelResult:
        started = time.monotonic()
        try:
            resp = self.http.post(
                "/api/chat",
                json={
                    "model": self.model,
                    "stream": False,
                    "format": OUTPUT_SCHEMA,  # Ollama constrains decoding to this JSON schema
                    "options": {"temperature": 0, "num_ctx": NUM_CTX},
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": build_user_message(item)},
                    ],
                },
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ModelError(f"ollama: {exc.__class__.__name__}: {exc}") from exc

        data = resp.json()
        prompt_tokens = data.get("prompt_eval_count")
        if prompt_tokens and prompt_tokens >= NUM_CTX:
            raise ModelError(f"prompt filled the context window ({prompt_tokens} tokens)")
        try:
            assessment = RiskAssessment.model_validate(json.loads(data["message"]["content"]))
        except (KeyError, json.JSONDecodeError, ValidationError) as exc:
            raise ModelError(f"invalid assessment: {exc}") from exc

        return ModelResult(
            assessment=assessment,
            model=self.name,
            prompt_version=PROMPT_VERSION,
            latency_ms=int((time.monotonic() - started) * 1000),
            input_tokens=prompt_tokens,
            output_tokens=data.get("eval_count"),
        )
