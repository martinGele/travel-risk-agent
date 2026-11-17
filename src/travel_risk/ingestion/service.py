"""Fetch both feeds and store new advisory versions. Assessments get triggered from here."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import replace
from datetime import UTC, date, datetime

import httpx
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from travel_risk.config import get_settings
from travel_risk.ingestion import uk_fcdo, us_state
from travel_risk.ingestion.materiality import ChangeKind, classify
from travel_risk.ingestion.snapshot import AdvisorySnapshot, Source
from travel_risk.llm.base import RiskModel
from travel_risk.models import Advisory, SyncRun
from travel_risk.schemas import SyncResult

log = logging.getLogger(__name__)


def current_version(session: Session, source: str, country_iso: str) -> Advisory | None:
    return session.scalars(
        select(Advisory)
        .where(Advisory.source == source, Advisory.country_iso == country_iso)
        .order_by(Advisory.version.desc())
        .limit(1)
    ).first()


def merge_snapshots(items: list[AdvisorySnapshot]) -> AdvisorySnapshot:
    if len(items) == 1:
        return items[0]
    items = sorted(items, key=lambda s: (-s.level, s.title))
    top = items[0]
    dates = [s.source_updated_at for s in items if s.source_updated_at]
    return replace(
        top,
        regional=top.regional or len({s.level for s in items}) > 1,
        title=" / ".join(s.title for s in items),
        summary="\n\n".join(f"## {s.title}\n{s.summary}" for s in items),
        source_updated_at=max(dates) if dates else None,
    )


def store_snapshots(
    session: Session, source: Source, snapshots: Iterable[AdvisorySnapshot]
) -> tuple[int, int, list[Advisory]]:
    """Store changed versions. Returns (seen, created, versions that trigger assessments).

    Two US items can share a country (Gaza + West Bank -> PS, Bonaire + Saba -> BQ). They are
    merged into one version: the strictest level, both texts under their own titles, and the
    regional flag set when the levels differ, so the model can tell the areas apart.
    """
    grouped: dict[str, list[AdvisorySnapshot]] = {}
    seen = 0
    for snap in snapshots:
        seen += 1
        grouped.setdefault(snap.country_iso, []).append(snap)
    by_country = {iso: merge_snapshots(items) for iso, items in grouped.items()}

    created = 0
    triggering: list[Advisory] = []
    for iso, snap in sorted(by_country.items()):
        prev = current_version(session, source, iso)
        verdict = classify(snap, prev)
        if not verdict.store:
            continue
        if prev is not None:
            session.execute(
                update(Advisory)
                .where(Advisory.source == source, Advisory.country_iso == iso)
                .values(is_current=False)
            )
        row = Advisory(
            source=source,
            country_iso=iso,
            version=(prev.version + 1) if prev else 1,
            is_current=True,
            level=snap.level,
            source_level_label=snap.source_level_label,
            regional=snap.regional,
            alert_status=list(snap.alert_status),
            title=snap.title,
            summary=snap.summary,
            url=snap.url,
            published_at=snap.published_at,
            source_updated_at=snap.source_updated_at,
            source_edited_at=snap.source_edited_at,
            change_description=snap.change_description,
            change_kind=verdict.kind,
            triggers_assessment=verdict.triggers_assessment,
            content_hash=snap.content_hash,
        )
        session.add(row)
        created += 1
        if verdict.triggers_assessment:
            triggering.append(row)
        log.info("advisory %s/%s v%s: %s", source, iso, row.version, verdict.kind)
    session.flush()
    return seen, created, triggering


def _uk_snapshots(session: Session, client: httpx.Client) -> Iterable[AdvisorySnapshot]:
    """Only fetch country pages whose public_updated_at moved since our stored version."""
    for entry in uk_fcdo.fetch_index(client):
        prev = current_version(session, Source.UK_FCDO, entry.country_iso)
        if prev is not None and prev.source_updated_at == entry.public_updated_at:
            continue
        try:
            yield uk_fcdo.fetch_country(client, entry.slug)
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            log.warning("UK %s: fetch failed: %s", entry.slug, exc)


def sync_source(
    session: Session,
    source: Source,
    client: httpx.Client,
    model: RiskModel | None = None,
    today: date | None = None,
) -> SyncResult:
    run = SyncRun(source=source)
    session.add(run)
    session.flush()
    errors: list[str] = []
    seen = created = material = 0
    try:
        if source is Source.US_STATE:
            snaps: Iterable[AdvisorySnapshot] = us_state.fetch(client)
        else:
            snaps = _uk_snapshots(session, client)
        seen, created, triggering = store_snapshots(session, source, snaps)
        material = len(triggering)
    except (httpx.HTTPError, ValueError) as exc:
        log.exception("sync %s failed", source)
        errors.append(str(exc))
        run.error = str(exc)
    run.finished_at = datetime.now(UTC)
    run.items_seen, run.versions_created, run.material_changes = seen, created, material
    session.commit()  # advisories are saved even if assessment below fails

    assessments = 0
    if not errors and triggering and model is not None:
        assessments = run_trigger_1(session, triggering, model, today or date.today())
    return SyncResult(
        source=source, items_seen=seen, versions_created=created,
        material_changes=material, assessments_created=assessments, errors=errors,
    )


def run_trigger_1(
    session: Session, advisories: list[Advisory], model: RiskModel, today: date
) -> int:
    """MATCHING_RULES.md §4 trigger 1: assess candidate trips for each material version."""
    from travel_risk.assess.pipeline import assess_advisory_change

    total = 0
    for adv in advisories:
        total += len(assess_advisory_change(session, adv, model, today))
        session.commit()
    return total


def make_client() -> httpx.Client:
    s = get_settings()
    return httpx.Client(
        timeout=s.http_timeout_seconds,
        headers={"User-Agent": s.user_agent},
        follow_redirects=True,
    )


SYNC_LOCK_ID = 7_321_001  # arbitrary, unique to this app


def sync_all(session: Session, model: RiskModel | None = None) -> list[SyncResult]:
    """Poll both feeds. A Postgres advisory lock stops two syncs overlapping (two containers,
    or a scheduled run arriving while a manual one is still going)."""
    from sqlalchemy import text

    got = session.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": SYNC_LOCK_ID}).scalar()
    if not got:
        return [SyncResult(source="all", items_seen=0, versions_created=0, material_changes=0,
                           errors=["another sync is already running"])]
    try:
        with make_client() as client:
            return [sync_source(session, src, client, model) for src in Source]
    finally:
        session.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": SYNC_LOCK_ID})
        session.commit()


__all__ = ["ChangeKind", "store_snapshots", "sync_all", "sync_source", "current_version"]
