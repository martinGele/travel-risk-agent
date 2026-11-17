"""Fetch both feeds and store new advisory versions. Assessments get triggered from here."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import UTC, datetime

import httpx
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from travel_risk.config import get_settings
from travel_risk.ingestion import uk_fcdo, us_state
from travel_risk.ingestion.materiality import ChangeKind, classify
from travel_risk.ingestion.snapshot import AdvisorySnapshot, Source
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


def store_snapshots(
    session: Session, source: Source, snapshots: Iterable[AdvisorySnapshot]
) -> tuple[int, int, list[Advisory]]:
    """Store changed versions. Returns (seen, created, versions that trigger assessments).

    Two US items can share a country (Gaza + West Bank -> PS, Bonaire + Saba -> BQ). We keep the
    strictest one per country so the stored "current" version is the one that matters for safety.
    """
    by_country: dict[str, AdvisorySnapshot] = {}
    seen = 0
    for snap in snapshots:
        seen += 1
        existing = by_country.get(snap.country_iso)
        if existing is None or snap.level > existing.level:
            by_country[snap.country_iso] = snap

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


def sync_source(session: Session, source: Source, client: httpx.Client) -> SyncResult:
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
        # Week 3: enqueue assessments for `triggering` (MATCHING_RULES.md §4, trigger 1).
    except (httpx.HTTPError, ValueError) as exc:
        log.exception("sync %s failed", source)
        errors.append(str(exc))
        run.error = str(exc)
    run.finished_at = datetime.now(UTC)
    run.items_seen, run.versions_created, run.material_changes = seen, created, material
    session.commit()
    return SyncResult(
        source=source, items_seen=seen, versions_created=created,
        material_changes=material, errors=errors,
    )


def make_client() -> httpx.Client:
    s = get_settings()
    return httpx.Client(
        timeout=s.http_timeout_seconds,
        headers={"User-Agent": s.user_agent},
        follow_redirects=True,
    )


def sync_all(session: Session) -> list[SyncResult]:
    with make_client() as client:
        return [sync_source(session, src, client) for src in Source]


__all__ = ["ChangeKind", "store_snapshots", "sync_all", "sync_source", "current_version"]
