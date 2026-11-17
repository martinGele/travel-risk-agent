"""Read models for the review queue and alert history. Always filtered by organisation."""

from __future__ import annotations

from sqlalchemy import case, select
from sqlalchemy.orm import Session

from travel_risk.assess.messages import country_name, format_dates
from travel_risk.models import Advisory, Assessment, Notification, Review, Traveller, Trip

QUEUE_STATUSES = {
    "pending": ("pending",),
    "digest": ("digest", "digested"),
    "dismissed": ("no_action",),
    "decided": ("approved", "edited", "rejected"),
    "superseded": ("superseded",),
}
_SEVERITY_ORDER = case({"high": 0, "medium": 1, "low": 2}, value=Assessment.severity, else_=3)


def list_assessments(session: Session, org_id: int, statuses: tuple[str, ...]) -> list[dict]:
    rows = session.execute(
        select(Assessment, Trip, Traveller, Advisory)
        .join(Trip, Assessment.trip_id == Trip.id)
        .join(Traveller, Trip.traveller_id == Traveller.id)
        .join(Advisory, Assessment.advisory_id == Advisory.id)
        .where(Assessment.organisation_id == org_id, Assessment.status.in_(statuses))
        .order_by(_SEVERITY_ORDER, Trip.start_date, Assessment.id)
    ).all()
    return [
        {
            "id": a.id,
            "status": a.status,
            "route": a.route,
            "route_reasons": a.route_reasons,
            "affected": a.affected,
            "severity": a.severity,
            "confidence": round(a.confidence, 2),
            "reason": a.reason,
            "action": a.action,
            "drafted_message": a.drafted_message,
            "model": a.model,
            "prompt_version": a.prompt_version,
            "created_at": a.created_at,
            "trip": {
                "id": t.id,
                "city": t.city,
                "country_iso": t.country_iso,
                "country": country_name(t.country_iso),
                "start_date": t.start_date,
                "end_date": t.end_date,
                "dates": format_dates(t.start_date, t.end_date),
            },
            "traveller": {"id": tr.id, "name": tr.name, "email": tr.email},
            "advisory": {
                "id": adv.id,
                "source": adv.source,
                "level": adv.level,
                "label": adv.source_level_label,
                "regional": adv.regional,
                "version": adv.version,
                "change_kind": adv.change_kind,
                "url": adv.url,
                "title": adv.title,
            },
        }
        for a, t, tr, adv in rows
    ]


def list_alerts(session: Session, org_id: int) -> list[dict]:
    rows = session.execute(
        select(Notification, Assessment, Trip, Traveller, Review)
        .join(Assessment, Notification.assessment_id == Assessment.id)
        .join(Trip, Assessment.trip_id == Trip.id)
        .join(Traveller, Trip.traveller_id == Traveller.id)
        .outerjoin(Review, Notification.review_id == Review.id)
        .where(Notification.organisation_id == org_id)
        .order_by(Notification.id.desc())
    ).all()
    return [
        {
            "id": n.id,
            "assessment_id": a.id,
            "channel": n.channel,
            "status": n.status,
            "error": n.error,
            "sent_at": n.sent_at,
            "traveller": tr.name,
            "destination": f"{t.city + ', ' if t.city else ''}{country_name(t.country_iso)}",
            "severity": a.severity,
            "reviewer": r.reviewer if r else None,
            "decision": r.decision if r else "digest",
            "message": (r.edited_message if r and r.edited_message else a.drafted_message),
        }
        for n, a, t, tr, r in rows
    ]
