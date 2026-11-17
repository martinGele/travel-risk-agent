"""Typed contracts shared by the LLM layer, the API and the evals."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class RiskAssessment(BaseModel):
    """The LLM's structured output for one (advisory, trip group). See docs/SEVERITY_RUBRIC.md."""

    affected: bool
    severity: Literal["low", "medium", "high"]
    reason: str = Field(description="One sentence that names the source and cites the advisory.")
    action: str = Field(description="An instruction the traveller can follow in 30 seconds.")
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _unaffected_is_low(self) -> RiskAssessment:
        if not self.affected and self.severity != "low":
            raise ValueError("affected=false must pair with severity='low' (rubric)")
        return self


class TripImportResult(BaseModel):
    accepted: int
    rejected: list[dict]


class SyncResult(BaseModel):
    source: str
    items_seen: int
    versions_created: int
    material_changes: int
    errors: list[str] = []
