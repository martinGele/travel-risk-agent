from __future__ import annotations

from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, UploadFile, status
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from travel_risk.api.auth import require_operator, require_org
from travel_risk.db import get_session
from travel_risk.ingestion.service import sync_all
from travel_risk.models import Advisory, Organisation
from travel_risk.schemas import SyncResult, TripImportResult

app = FastAPI(
    title="Travel Risk Agent",
    version="0.1.0",
    description="Matches official travel advisories against upcoming trips; humans approve alerts.",
)

SessionDep = Annotated[Session, Depends(get_session)]
OrgDep = Annotated[Organisation, Depends(require_org)]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready")
def ready(session: SessionDep) -> dict[str, str]:
    session.execute(text("SELECT 1"))
    return {"status": "ready"}


@app.post(
    "/v1/advisories/sync",
    dependencies=[Depends(require_operator)],
    response_model=list[SyncResult],
)
def sync_advisories(session: SessionDep) -> list[SyncResult]:
    """Poll both feeds now. In production EventBridge Scheduler calls this every 30 minutes."""
    return sync_all(session)


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


# ---- Week 3 endpoints: signatures fixed now so auth and scoping are in place from day one ----

def _not_yet() -> HTTPException:
    return HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "planned for week 3")


@app.post("/v1/orgs/{org_id}/trips/import", response_model=TripImportResult)
def import_trips(org: OrgDep, file: UploadFile) -> TripImportResult:
    raise _not_yet()


@app.get("/v1/orgs/{org_id}/assessments")
def list_assessments(org: OrgDep, status_: str = "pending") -> list[dict]:
    raise _not_yet()


@app.post("/v1/orgs/{org_id}/assessments/{assessment_id}/review")
def review_assessment(org: OrgDep, assessment_id: int) -> dict:
    raise _not_yet()


@app.get("/v1/orgs/{org_id}/alerts")
def list_alerts(org: OrgDep) -> list[dict]:
    raise _not_yet()
