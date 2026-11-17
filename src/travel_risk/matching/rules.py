"""Deterministic matching and routing. Contract: docs/MATCHING_RULES.md §2, §5, §6."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from travel_risk.schemas import RiskAssessment

REVIEW_CONFIDENCE_THRESHOLD = 0.7
SOURCES_DISAGREE_GAP = 2

# Spellings customers use for the same city. Extend from real data; every entry needs a test.
CITY_ALIASES: dict[str, str] = {
    "kiev": "kyiv",
    "bombay": "mumbai",
    "calcutta": "kolkata",
    "madras": "chennai",
    "peking": "beijing",
    "saigon": "ho chi minh city",
    "hcmc": "ho chi minh city",
    "bayrut": "beirut",
    "beyrouth": "beirut",
    "al quds": "jerusalem",
    "new delhi": "delhi",
    "ny": "new york",
    "nyc": "new york",
}


class Route(StrEnum):
    REVIEW = "review"
    DIGEST = "digest"
    NO_ACTION = "no_action"


@dataclass(frozen=True)
class TripLike:
    country_iso: str
    city: str | None
    start_date: date
    end_date: date


def is_candidate(trip: TripLike, advisory_country: str, advisory_level: int, today: date) -> bool:
    """§2: same country, trip not yet finished, advisory above normal precautions."""
    return (
        trip.country_iso == advisory_country
        and trip.end_date >= today
        and advisory_level >= 2
    )


def normalise_city(city: str | None) -> str:
    if not city:
        return ""
    text = unicodedata.normalize("NFKD", city).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9 ]+", " ", text.lower())
    text = re.sub(r"\s+", " ", text).strip()
    return CITY_ALIASES.get(text, text)


def group_key(advisory_id: int, trip: TripLike) -> str:
    """§5: trips sharing this key get one LLM call."""
    return "|".join(
        [
            str(advisory_id),
            trip.country_iso,
            normalise_city(trip.city),
            trip.start_date.isoformat(),
            trip.end_date.isoformat(),
        ]
    )


@dataclass(frozen=True)
class RoutingDecision:
    route: Route
    reasons: tuple[str, ...]


def route(
    assessment: RiskAssessment,
    advisory_level: int,
    advisory_regional: bool,
    other_source_level: int | None,
) -> RoutingDecision:
    """§6: any reason sends it to review. The LLM can escalate, never suppress."""
    reasons: list[str] = []
    if advisory_level >= 3:
        reasons.append("high_level")
    if advisory_regional:
        reasons.append("regional")
    if (
        other_source_level is not None
        and abs(other_source_level - advisory_level) >= SOURCES_DISAGREE_GAP
    ):
        reasons.append("sources_disagree")
    if not assessment.affected and advisory_level >= 3:
        reasons.append("llm_dismissed_high")
    if assessment.severity == "high":
        reasons.append("high_severity")
    if assessment.confidence < REVIEW_CONFIDENCE_THRESHOLD:
        reasons.append("low_confidence")

    if reasons:
        return RoutingDecision(Route.REVIEW, tuple(reasons))
    if assessment.affected:
        return RoutingDecision(Route.DIGEST, ())
    return RoutingDecision(Route.NO_ACTION, ())
