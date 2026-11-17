"""Model layer interface (week 3). Hosted API and local Ollama both implement `RiskModel`."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from travel_risk.schemas import RiskAssessment

PROMPT_VERSION = "v0"


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


class RiskModel(Protocol):
    name: str

    def assess(self, item: AssessmentInput) -> ModelResult: ...
