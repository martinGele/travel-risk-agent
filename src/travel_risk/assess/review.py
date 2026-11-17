"""The human decision step, shared by the REST API and the review page."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from travel_risk.models import Advisory, Assessment, Notification, Organisation, Review, Trip
from travel_risk.notify.notifier import Delivery, Notifier, channel_for
from travel_risk.schemas import ReviewRequest

DECISION_STATUS = {"approve": "approved", "edit": "edited", "reject": "rejected"}


class ReviewError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code, self.detail = status_code, detail


def get_org_assessment(session: Session, org: Organisation, assessment_id: int) -> Assessment:
    a = session.scalars(
        select(Assessment).where(
            Assessment.id == assessment_id, Assessment.organisation_id == org.id
        )
    ).first()
    if a is None:
        raise ReviewError(404, "assessment not found")
    return a


def apply_review(
    session: Session, org: Organisation, assessment_id: int, req: ReviewRequest,
    notifier: Notifier,
) -> tuple[Assessment, Notification | None]:
    a = get_org_assessment(session, org, assessment_id)
    if a.status != "pending":
        raise ReviewError(409, f"assessment is {a.status}, not pending")

    review = Review(
        assessment_id=a.id, decision=req.decision, reviewer=req.reviewer,
        edited_message=req.edited_message if req.decision == "edit" else None,
    )
    session.add(review)
    a.status = DECISION_STATUS[req.decision]
    session.flush()

    notification = None
    if req.decision != "reject":
        message = req.edited_message if req.decision == "edit" else a.drafted_message
        notification = send(session, org, a, message or a.drafted_message, notifier, review.id)
    session.commit()
    return a, notification


SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}


def merged_message(org: Organisation, trip: Trip, items: list[tuple[Assessment, Advisory]]) -> str:
    """One message per trip: every source's reason, and the most severe source's action."""
    from travel_risk.assess.messages import draft_message

    items = sorted(items, key=lambda x: SEVERITY_RANK.get(x[0].severity, 3))
    if len(items) == 1:
        return items[0][0].drafted_message
    top, top_adv = items[0]
    return draft_message(
        traveller_name=trip.traveller.name, org_name=org.name, city=trip.city,
        country_iso=trip.country_iso, start=trip.start_date, end=trip.end_date,
        source=top_adv.source, advisory_url=top_adv.url,
        reason="\n".join(a.reason for a, _ in items), action=top.action,
    )


def apply_trip_review(
    session: Session, org: Organisation, assessment_ids: list[int], decision: str,
    reviewer: str, message: str | None, notifier: Notifier,
) -> tuple[list[Assessment], Notification | None]:
    """Decide several pending assessments for the same trip at once and send one message."""
    items = [get_org_assessment(session, org, i) for i in assessment_ids]
    if not items:
        raise ReviewError(400, "no assessments given")
    if len({a.trip_id for a in items}) != 1:
        raise ReviewError(400, "assessments belong to different trips")
    if any(a.status != "pending" for a in items):
        raise ReviewError(409, "an assessment in this group is no longer pending")
    items.sort(key=lambda a: SEVERITY_RANK.get(a.severity, 3))
    trip = session.get(Trip, items[0].trip_id)
    default = merged_message(org, trip, [(a, session.get(Advisory, a.advisory_id)) for a in items])
    edited = decision == "approve" and message is not None and message.strip() != default.strip()
    final = message.strip() if edited else default
    kind = "edit" if edited else decision

    reviews = []
    for a in items:
        r = Review(assessment_id=a.id, decision=kind, reviewer=reviewer,
                   edited_message=final if kind == "edit" else None)
        session.add(r)
        a.status = DECISION_STATUS[kind]
        reviews.append(r)
    session.flush()
    notification = None
    if decision != "reject":
        # One message, attached to the most severe assessment; the others are covered by it.
        notification = send(session, org, items[0], final, notifier, reviews[0].id)
    session.commit()
    return items, notification


def _already_told(session: Session, a: Assessment) -> bool:
    """§7 de-duplication: was this traveller already sent this level of risk for this source?"""
    adv = session.get(Advisory, a.advisory_id)
    prior = session.execute(
        select(Advisory.level, Advisory.regional)
        .select_from(Notification)
        .join(Assessment, Notification.assessment_id == Assessment.id)
        .join(Advisory, Assessment.advisory_id == Advisory.id)
        .where(
            Assessment.trip_id == a.trip_id,
            Assessment.id != a.id,
            Notification.status == "sent",
            Advisory.source == adv.source,
            Advisory.country_iso == adv.country_iso,
        )
        .order_by(Notification.id.desc())
        .limit(1)
    ).first()
    if prior is None:
        return False
    level, regional = prior
    # Re-send only if the risk went up or its scope changed. Level drops always go out.
    return adv.level == level and adv.regional == regional


def send(
    session: Session, org: Organisation, a: Assessment, message: str, notifier: Notifier,
    review_id: int | None,
) -> Notification:
    trip = session.get(Trip, a.trip_id)
    channel = channel_for(org.notify_channel, org.slack_webhook_url)
    n = Notification(
        organisation_id=org.id, assessment_id=a.id, review_id=review_id,
        channel=channel, status="queued",
    )
    session.add(n)
    session.flush()
    if _already_told(session, a):
        n.status = "skipped_duplicate"
        return n
    result = notifier.deliver(
        Delivery(
            notification_id=n.id, channel=channel, message=message,
            slack_webhook_url=org.slack_webhook_url, slack_user_id=trip.traveller.slack_id,
            email_to=trip.traveller.email,
        )
    )
    n.status = "sent" if result.ok else "failed"
    n.error = result.error
    n.sent_at = datetime.now(UTC) if result.ok else None
    return n
