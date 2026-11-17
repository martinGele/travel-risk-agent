"""Daily digest: one message per organisation to its travel manager, listing low-severity alerts.

Digest items skip per-item approval (MATCHING_RULES.md §6), so they go to the manager, who can
forward anything worth passing on. Nothing in the digest reaches a traveller directly.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from travel_risk.assess.messages import SOURCE_NAMES, country_name, format_dates
from travel_risk.models import Advisory, Assessment, Notification, Organisation, Traveller, Trip
from travel_risk.notify.notifier import Delivery, Notifier, channel_for


def build_digest(org: Organisation, rows: list[tuple[Assessment, Trip, Traveller, Advisory]],
                 today: date) -> str:
    lines = [
        f"Travel risk digest for {org.name}, {today.strftime('%-d %b %Y')}",
        "",
        f"{len(rows)} low-severity advisory update(s) for upcoming trips. No traveller has been "
        "contacted about these; forward anything you think they should see.",
        "",
    ]
    for a, t, tr, adv in rows:
        place = f"{t.city}, {country_name(t.country_iso)}" if t.city else country_name(
            t.country_iso)
        lines += [
            f"- {tr.name}: {place}, {format_dates(t.start_date, t.end_date)}",
            f"  {SOURCE_NAMES.get(adv.source, adv.source)}: {adv.source_level_label}",
            f"  {a.reason}",
            f"  Suggested action: {a.action}",
            "",
        ]
    return "\n".join(lines).rstrip() + "\n"


def send_digests(session: Session, notifier: Notifier, today: date) -> dict[int, int]:
    """Send one digest per organisation with open digest items. Returns {org_id: items}."""
    sent: dict[int, int] = {}
    for org in session.scalars(select(Organisation)):
        rows = session.execute(
            select(Assessment, Trip, Traveller, Advisory)
            .join(Trip, Assessment.trip_id == Trip.id)
            .join(Traveller, Trip.traveller_id == Traveller.id)
            .join(Advisory, Assessment.advisory_id == Advisory.id)
            .where(Assessment.organisation_id == org.id, Assessment.status == "digest",
                   Trip.end_date >= today)
            .order_by(Trip.start_date)
        ).all()
        if not rows:
            continue
        channel = channel_for(org.notify_channel, org.slack_webhook_url)
        notes = []
        for a, *_ in rows:
            n = Notification(organisation_id=org.id, assessment_id=a.id, channel=channel,
                             status="queued")
            session.add(n)
            notes.append(n)
        session.flush()
        result = notifier.deliver(Delivery(
            notification_id=notes[0].id, channel=channel,
            message=build_digest(org, [tuple(r) for r in rows], today),
            slack_webhook_url=org.slack_webhook_url, email_to=org.contact_email,
            subject=f"Travel risk digest: {len(rows)} update(s)",
        ))
        now = datetime.now(UTC)
        for (a, *_), n in zip(rows, notes, strict=True):
            n.status = "sent" if result.ok else "failed"
            n.error = result.error
            n.sent_at = now if result.ok else None
            if result.ok:
                a.status = "digested"
        sent[org.id] = len(rows)
        session.commit()
    return sent
