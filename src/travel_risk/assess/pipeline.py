"""Rules first, model second, routing third. Contract: docs/MATCHING_RULES.md §2 and §4–§7."""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Iterable
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from travel_risk.assess.messages import draft_message
from travel_risk.llm.base import AssessmentInput, ModelError, ModelResult, RiskModel
from travel_risk.matching.rules import Route, TripLike, group_key, is_candidate, route
from travel_risk.models import Advisory, Assessment, Organisation, Trip
from travel_risk.schemas import RiskAssessment

log = logging.getLogger(__name__)

ROUTE_STATUS = {Route.REVIEW: "pending", Route.DIGEST: "digest", Route.NO_ACTION: "no_action"}
OPEN_STATUSES = ("pending", "digest")
# Statuses meaning the traveller has been (or is about to be) told about this advisory.
NOTIFIED_STATUSES = ("pending", "digest", "approved", "edited", "digested")


def current_advisory(session: Session, source: str, country_iso: str) -> Advisory | None:
    return session.scalars(
        select(Advisory).where(
            Advisory.source == source, Advisory.country_iso == country_iso, Advisory.is_current
        )
    ).first()


def _other_source_level(session: Session, advisory: Advisory) -> int | None:
    other = session.scalars(
        select(Advisory.level).where(
            Advisory.country_iso == advisory.country_iso,
            Advisory.source != advisory.source,
            Advisory.is_current,
        )
    ).first()
    return other


def _previous_level(session: Session, advisory: Advisory) -> int | None:
    if advisory.version <= 1:
        return None
    return session.scalars(
        select(Advisory.level).where(
            Advisory.source == advisory.source,
            Advisory.country_iso == advisory.country_iso,
            Advisory.version == advisory.version - 1,
        )
    ).first()


def _trip_like(trip: Trip) -> TripLike:
    return TripLike(trip.country_iso, trip.city, trip.start_date, trip.end_date)


def assess_advisory_change(
    session: Session, advisory: Advisory, model: RiskModel, today: date
) -> list[Assessment]:
    """Trigger 1 (§4): a material advisory version arrived; assess every candidate trip."""
    trips = session.scalars(
        select(Trip).where(Trip.country_iso == advisory.country_iso, Trip.end_date >= today)
    ).all()
    pairs = [
        (t, advisory)
        for t in trips
        if is_candidate(_trip_like(t), advisory.country_iso, advisory.level, today)
    ]
    if advisory.change_kind == "level_down":
        # Travellers already told about this risk should hear that it eased, even at level 1.
        already = {t.id for t, _ in pairs}
        pairs += [(t, advisory) for t in _previously_notified(session, advisory, trips)
                  if t.id not in already]
    return assess_pairs(session, pairs, model)


def _previously_notified(session: Session, advisory: Advisory, trips: list[Trip]) -> list[Trip]:
    if not trips:
        return []
    ids = set(
        session.scalars(
            select(Assessment.trip_id)
            .join(Advisory, Assessment.advisory_id == Advisory.id)
            .where(
                Assessment.trip_id.in_([t.id for t in trips]),
                Assessment.affected,
                Assessment.status.in_(NOTIFIED_STATUSES),
                Advisory.source == advisory.source,
                Advisory.country_iso == advisory.country_iso,
            )
        )
    )
    return [t for t in trips if t.id in ids]


def assess_new_trips(
    session: Session, trips: Iterable[Trip], model: RiskModel, today: date
) -> list[Assessment]:
    """Trigger 2 (§4): new trips are checked against the current version from each source."""
    pairs: list[tuple[Trip, Advisory]] = []
    cache: dict[tuple[str, str], Advisory | None] = {}
    for trip in trips:
        for source in ("us_state", "uk_fcdo"):
            key = (source, trip.country_iso)
            if key not in cache:
                cache[key] = current_advisory(session, source, trip.country_iso)
            adv = cache[key]
            if adv and is_candidate(_trip_like(trip), adv.country_iso, adv.level, today):
                pairs.append((trip, adv))
    return assess_pairs(session, pairs, model)


def _failsafe(model: RiskModel, advisory: Advisory, error: str) -> ModelResult:
    """If the model fails, the case goes to a human. It is never dropped."""
    return ModelResult(
        assessment=RiskAssessment(
            affected=True,
            severity="high" if advisory.level >= 4 else "medium",
            reason=f"Automatic assessment failed ({error}); a person must read the advisory.",
            action="Wait for the travel team to confirm whether this trip can go ahead.",
            confidence=0.0,
        ),
        model=f"{model.name} (failed)",
        prompt_version="failsafe",
        latency_ms=0,
    )


def assess_pairs(
    session: Session, pairs: list[tuple[Trip, Advisory]], model: RiskModel
) -> list[Assessment]:
    # Skip (trip, advisory version) pairs already assessed, so re-runs are idempotent.
    if not pairs:
        return []
    done = {
        (trip_id, advisory_id)
        for trip_id, advisory_id in session.execute(
            select(Assessment.trip_id, Assessment.advisory_id).where(
                Assessment.trip_id.in_({t.id for t, _ in pairs})
            )
        )
    }
    groups: dict[str, list[tuple[Trip, Advisory]]] = defaultdict(list)
    for trip, adv in pairs:
        if (trip.id, adv.id) not in done:
            groups[group_key(adv.id, _trip_like(trip))].append((trip, adv))

    orgs: dict[int, Organisation] = {}
    created: list[Assessment] = []
    for key, members in groups.items():
        first_trip, adv = members[0]
        other_level = _other_source_level(session, adv)
        item = AssessmentInput(
            source=adv.source,
            country_iso=adv.country_iso,
            advisory_level=adv.level,
            advisory_label=adv.source_level_label,
            advisory_regional=adv.regional,
            advisory_text=adv.summary,
            city=first_trip.city or "",
            start_date=first_trip.start_date,
            end_date=first_trip.end_date,
            other_source_level=other_level,
            change_kind=adv.change_kind,
            previous_level=_previous_level(session, adv),
        )
        extra_reasons: tuple[str, ...] = ()
        try:
            result = model.assess(item)
        except ModelError as exc:
            log.warning("model failed for group %s: %s", key, exc)
            result = _failsafe(model, adv, str(exc))
            extra_reasons = ("model_error",)
        decision = route(result.assessment, adv.level, adv.regional, other_level)
        reasons = extra_reasons + decision.reasons

        for trip, _ in members:
            org = orgs.get(trip.organisation_id) or session.get(Organisation, trip.organisation_id)
            orgs[trip.organisation_id] = org
            ra = result.assessment
            row = Assessment(
                organisation_id=trip.organisation_id,
                trip_id=trip.id,
                advisory_id=adv.id,
                group_key=key,
                affected=ra.affected,
                severity=ra.severity,
                reason=ra.reason,
                action=ra.action,
                confidence=ra.confidence,
                drafted_message=draft_message(
                    traveller_name=trip.traveller.name, org_name=org.name, city=trip.city,
                    country_iso=trip.country_iso, start=trip.start_date, end=trip.end_date,
                    source=adv.source, advisory_url=adv.url, reason=ra.reason, action=ra.action,
                ),
                route=decision.route,
                route_reasons=list(reasons),
                status=ROUTE_STATUS[decision.route],
                model=result.model,
                prompt_version=result.prompt_version,
                latency_ms=result.latency_ms,
                trace_id=result.request_id,
            )
            session.add(row)
            session.flush()
            _supersede(session, trip, adv, row)
            created.append(row)
    session.flush()
    return created


def _supersede(session: Session, trip: Trip, advisory: Advisory, new: Assessment) -> None:
    """§7: open assessments from older versions of the same (source, country) are replaced."""
    older = session.scalars(
        select(Assessment)
        .join(Advisory, Assessment.advisory_id == Advisory.id)
        .where(
            Assessment.trip_id == trip.id,
            Assessment.id != new.id,
            Assessment.status.in_(OPEN_STATUSES),
            Advisory.source == advisory.source,
            Advisory.country_iso == advisory.country_iso,
            Advisory.version < advisory.version,
        )
    ).all()
    for a in older:
        a.status = "superseded"
        a.superseded_by_id = new.id


def load_trips(session: Session, ids: Iterable[int]) -> list[Trip]:
    return list(
        session.scalars(
            select(Trip).options(joinedload(Trip.traveller)).where(Trip.id.in_(list(ids)))
        )
    )
