from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Annotated

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, UploadFile
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from travel_risk.api.auth import require_operator, require_org
from travel_risk.assess.pipeline import assess_new_trips, load_trips
from travel_risk.assess.queries import QUEUE_STATUSES, list_alerts, list_assessments
from travel_risk.assess.review import ReviewError, apply_review
from travel_risk.config import get_settings
from travel_risk.db import get_session, get_sessionmaker
from travel_risk.ingestion.service import sync_all
from travel_risk.llm.factory import get_model
from travel_risk.models import Advisory, Organisation
from travel_risk.notify.notifier import DefaultNotifier, Notifier
from travel_risk.schemas import ReviewRequest, SyncResult, TripImportResult
from travel_risk.trips.csv_import import import_trips, parse_csv
from travel_risk.web.routes import router as web_router

MAX_CSV_BYTES = 5 * 1024 * 1024

app = FastAPI(
    title="Travel Risk Agent",
    version="0.2.0",
    description="Matches official travel advisories against upcoming trips; humans approve alerts.",
)
app.include_router(web_router)

SessionDep = Annotated[Session, Depends(get_session)]
OrgDep = Annotated[Organisation, Depends(require_org)]


def get_notifier() -> Notifier:
    return DefaultNotifier()


def _assess_trips_job(trip_ids: list[int]) -> None:
    """Runs after the import response is sent, with its own session."""
    with get_sessionmaker()() as session:
        assess_new_trips(session, load_trips(session, trip_ids), get_model(), date.today())
        session.commit()


def get_trip_assessor() -> Callable[[list[int]], None]:
    return _assess_trips_job


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready")
def ready(session: SessionDep) -> dict[str, str]:
    session.execute(text("SELECT 1"))
    return {"status": "ready"}


def _sync_job() -> None:
    with get_sessionmaker()() as session:
        sync_all(session, get_model())


@app.post("/v1/advisories/sync", dependencies=[Depends(require_operator)])
def sync_advisories(
    session: SessionDep, background: BackgroundTasks, wait: bool = True
) -> list[SyncResult] | dict:
    """Poll both feeds and assess affected trips.

    The scheduler calls this with wait=false: EventBridge gives up after 5 seconds, so the sync
    runs in the background and the call returns at once.
    """
    if not wait:
        background.add_task(_sync_job)
        return {"status": "started"}
    return sync_all(session, get_model())


@app.post("/v1/digests/send", dependencies=[Depends(require_operator)])
def send_digests_now(
    session: SessionDep, notifier: Annotated[Notifier, Depends(get_notifier)]
) -> dict:
    """Send each organisation's daily digest. EventBridge calls this once a day."""
    from travel_risk.notify.digest import send_digests

    sent = send_digests(session, notifier, date.today())
    return {"organisations": len(sent), "items": sum(sent.values())}


@app.post("/v1/maintenance/purge", dependencies=[Depends(require_operator)])
def purge_old_trips(session: SessionDep) -> dict:
    """Delete trips that ended more than the retention period ago (GDPR, brief §9)."""
    from datetime import timedelta

    from sqlalchemy import delete

    from travel_risk.models import Trip

    cutoff = date.today() - timedelta(days=get_settings().trip_retention_days)
    deleted = session.execute(delete(Trip).where(Trip.end_date < cutoff)).rowcount
    session.commit()
    return {"deleted_trips": deleted, "cutoff": cutoff.isoformat()}


@app.get("/v1/advisories/current")
def current_advisories(session: SessionDep, country_iso: str | None = None) -> list[dict]:
    """Public data only: the latest version per (source, country)."""
    q = select(Advisory).where(Advisory.is_current)
    if country_iso:
        q = q.where(Advisory.country_iso == country_iso.upper())
    return [
        {
            "source": a.source, "country_iso": a.country_iso, "level": a.level,
            "label": a.source_level_label, "regional": a.regional, "version": a.version,
            "change_kind": a.change_kind, "url": a.url,
            "source_updated_at": a.source_updated_at,
        }
        for a in session.scalars(q.order_by(Advisory.country_iso, Advisory.source))
    ]


@app.post("/v1/orgs/{org_id}/trips/import", response_model=TripImportResult)
async def import_trips_csv(
    org: OrgDep,
    session: SessionDep,
    file: UploadFile,
    background: BackgroundTasks,
    assessor: Annotated[Callable[[list[int]], None], Depends(get_trip_assessor)],
) -> TripImportResult:
    data = await file.read(MAX_CSV_BYTES + 1)
    if len(data) > MAX_CSV_BYTES:
        raise HTTPException(413, "CSV larger than 5 MB")
    parsed = parse_csv(data, date.today(), day_first=get_settings().csv_day_first)
    outcome = import_trips(session, org.id, parsed)
    session.commit()
    trip_ids = [t.id for t in outcome.created]
    if trip_ids:
        background.add_task(assessor, trip_ids)
    return TripImportResult(
        accepted=len(outcome.created),
        duplicates=outcome.duplicates,
        rejected=parsed.rejected,
        warnings=parsed.warnings,
        trips_queued_for_assessment=len(trip_ids),
    )


@app.get("/v1/orgs/{org_id}/assessments")
def get_assessments(
    org: OrgDep,
    session: SessionDep,
    status: Annotated[str, Query(pattern="^(" + "|".join(QUEUE_STATUSES) + ")$")] = "pending",
) -> list[dict]:
    """Review queue. status: pending | digest | dismissed | decided | superseded."""
    return list_assessments(session, org.id, QUEUE_STATUSES[status])


@app.post("/v1/orgs/{org_id}/assessments/{assessment_id}/review")
def review_assessment(
    org: OrgDep,
    session: SessionDep,
    assessment_id: int,
    body: ReviewRequest,
    notifier: Annotated[Notifier, Depends(get_notifier)],
) -> dict:
    """Approve, edit or reject. Approve and edit send the message immediately."""
    try:
        a, n = apply_review(session, org, assessment_id, body, notifier)
    except ReviewError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
    return {
        "assessment_id": a.id,
        "status": a.status,
        "notification": None if n is None else {
            "id": n.id, "channel": n.channel, "status": n.status, "error": n.error,
        },
    }


@app.get("/v1/orgs/{org_id}/alerts")
def get_alerts(org: OrgDep, session: SessionDep) -> list[dict]:
    """Sent (and failed) notifications, newest first."""
    return list_alerts(session, org.id)
