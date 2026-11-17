"""Model layer interface. Claude, the heuristic baseline and (week 5) Ollama all implement it."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from travel_risk.schemas import RiskAssessment


@dataclass(frozen=True)
class AssessmentInput:
    """Everything the model sees. Deliberately contains no personal data (MATCHING_RULES.md §5)."""

    source: str
    country_iso: str
    advisory_level: int
    advisory_label: str
    advisory_regional: bool
    advisory_text: str  # wrapped in a clearly marked data block by the prompt builder
    city: str
    start_date: date
    end_date: date
    other_source_level: int | None


@dataclass(frozen=True)
class ModelResult:
    assessment: RiskAssessment
    model: str
    prompt_version: str
    latency_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None
    request_id: str | None = None


class RiskModel(Protocol):
    name: str

    def assess(self, item: AssessmentInput) -> ModelResult: ...


class ModelError(RuntimeError):
    """Any failure to get a valid assessment. The pipeline turns it into a fail-safe review item."""
