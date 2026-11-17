"""Rules-only baseline. No network, no cost.

Used for offline tests and demos, and as the baseline row in the eval comparison table: the LLM
has to beat this on precision without losing recall.
"""

from __future__ import annotations

import time

from travel_risk.llm.base import AssessmentInput, ModelResult
from travel_risk.matching.rules import normalise_city
from travel_risk.schemas import RiskAssessment

SOURCE_NAMES = {"us_state": "US State Department", "uk_fcdo": "UK FCDO"}
_SEVERITY = {4: "high", 3: "medium", 2: "low", 1: "low"}
_ACTION = {
    4: "Do not travel. If you are already there, contact the travel team today about leaving.",
    3: "Reconsider this trip; if it is essential, agree a safety plan with the travel team first.",
    2: "Travel as planned, but read the advisory and avoid demonstrations and large crowds.",
    1: "No change needed; follow normal precautions.",
}


class HeuristicRiskModel:
    name = "heuristic-baseline"

    def assess(self, item: AssessmentInput) -> ModelResult:
        started = time.monotonic()
        level = item.advisory_level  # this advisory only (SEVERITY_RUBRIC.md)
        source = SOURCE_NAMES.get(item.source, item.source)
        city = normalise_city(item.city)
        city_named = bool(city) and city in normalise_city(item.advisory_text)

        if item.advisory_regional and not city_named:
            # Can't tell whether the city is inside the restricted area: say affected, flag it.
            reason = (
                f"{source} advice ({item.advisory_label}) covers parts of the country; "
                f"it is unclear whether {item.city or 'the destination'} is inside them."
            )
            confidence = 0.5
        else:
            reason = f"{source} advice for this country is {item.advisory_label}."
            confidence = 0.8

        if item.previous_level and item.advisory_level < item.previous_level:
            return ModelResult(
                assessment=RiskAssessment(
                    affected=True, severity="low",
                    reason=f"{source} lowered its advice to {item.advisory_label}.",
                    action="Restrictions eased: check the updated advisory before you travel.",
                    confidence=0.8,
                ),
                model=self.name, prompt_version="heuristic-v1",
                latency_ms=int((time.monotonic() - started) * 1000),
            )

        assessment = RiskAssessment(
            affected=True,  # the baseline never dismisses: perfect recall, weak precision
            severity=_SEVERITY[level],
            reason=reason,
            action=_ACTION[level],
            confidence=confidence,
        )
        return ModelResult(
            assessment=assessment,
            model=self.name,
            prompt_version="heuristic-v1",
            latency_ms=int((time.monotonic() - started) * 1000),
        )
