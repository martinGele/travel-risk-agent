"""Hosted model: Claude via the Anthropic API, with structured output."""

from __future__ import annotations

import json
import time

import anthropic
from pydantic import ValidationError

from travel_risk.llm.base import AssessmentInput, ModelError, ModelResult
from travel_risk.llm.prompt import OUTPUT_SCHEMA, PROMPT_VERSION, SYSTEM_PROMPT, build_user_message
from travel_risk.schemas import RiskAssessment

DEFAULT_MODEL = "claude-opus-5-5"


class ClaudeRiskModel:
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        effort: str = "medium",
        client: anthropic.Anthropic | None = None,
    ) -> None:
        self.name = model
        self.effort = effort
        # Credentials come from ANTHROPIC_API_KEY or an `ant auth login` profile.
        self.client = client or anthropic.Anthropic()

    def assess(self, item: AssessmentInput) -> ModelResult:
        started = time.monotonic()
        try:
            response = self.client.beta.messages.create(
                model=self.name,
                max_tokens=16000,
                # If a safety classifier declines, the API re-runs the request on a fallback
                # model inside the same call instead of returning a bare refusal.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                # Stable system prompt first so it can be cached across assessments.
                system=[
                    {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}
                ],
                messages=[{"role": "user", "content": build_user_message(item)}],
                output_config={
                    "effort": self.effort,
                    "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA},
                },
            )
        except anthropic.APIConnectionError as exc:
            raise ModelError(f"connection error: {exc}") from exc
        except anthropic.APIStatusError as exc:
            raise ModelError(f"API error {exc.status_code}: {exc.message}") from exc

        latency_ms = int((time.monotonic() - started) * 1000)
        if response.stop_reason == "refusal":
            raise ModelError("model declined to assess (refusal)")
        if response.stop_reason == "max_tokens":
            raise ModelError("output truncated (max_tokens)")

        text = next((b.text for b in response.content if b.type == "text"), None)
        if text is None:
            raise ModelError("no text block in response")
        try:
            assessment = RiskAssessment.model_validate(json.loads(text))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise ModelError(f"invalid assessment: {exc}") from exc

        return ModelResult(
            assessment=assessment,
            model=response.model,  # the fallback model's id if one served the request
            prompt_version=PROMPT_VERSION,
            latency_ms=latency_ms,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            request_id=getattr(response, "_request_id", None),
        )
