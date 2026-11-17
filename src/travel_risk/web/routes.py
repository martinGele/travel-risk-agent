"""Review page for travel managers. Server-rendered; the org API key lives in an httpOnly cookie."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from travel_risk.api.auth import hash_key
from travel_risk.assess.queries import QUEUE_STATUSES, list_alerts, list_assessments
from travel_risk.assess.review import ReviewError, apply_review
from travel_risk.db import get_session
from travel_risk.models import Assessment, Organisation
from travel_risk.notify.notifier import DefaultNotifier
from travel_risk.schemas import ReviewRequest

router = APIRouter(prefix="/ui", include_in_schema=False)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
KEY_COOKIE, NAME_COOKIE = "tra_key", "tra_reviewer"
TABS = [
    ("pending", "Needs review"), ("digest", "Daily digest"), ("dismissed", "Dismissed by model"),
    ("decided", "Decided"), ("sent", "Sent"), ("superseded", "Superseded"),
]
SessionDep = Annotated[Session, Depends(get_session)]


def _org_from_cookie(request: Request, session: Session) -> Organisation | None:
    key = request.cookies.get(KEY_COOKIE)
    if not key:
        return None
    return session.scalars(
        select(Organisation).where(Organisation.api_key_hash == hash_key(key))
    ).first()


def _to_login() -> RedirectResponse:
    return RedirectResponse("/ui/login", status_code=303)


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, error: str | None = None) -> Response:
    return templates.TemplateResponse(request, "login.html", {"error": error})


@router.post("/login")
def login(
    session: SessionDep,
    api_key: Annotated[str, Form()],
    reviewer: Annotated[str, Form()],
) -> Response:
    org = session.scalars(
        select(Organisation).where(Organisation.api_key_hash == hash_key(api_key.strip()))
    ).first()
    if org is None or not reviewer.strip():
        return RedirectResponse("/ui/login?error=1", status_code=303)
    resp = RedirectResponse("/ui", status_code=303)
    opts = {"httponly": True, "samesite": "strict", "max_age": 8 * 3600}
    resp.set_cookie(KEY_COOKIE, api_key.strip(), **opts)
    resp.set_cookie(NAME_COOKIE, reviewer.strip()[:256], **opts)
    return resp


@router.post("/logout")
def logout() -> Response:
    resp = _to_login()
    resp.delete_cookie(KEY_COOKIE)
    resp.delete_cookie(NAME_COOKIE)
    return resp


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def queue(request: Request, session: SessionDep, tab: str = "pending") -> Response:
    org = _org_from_cookie(request, session)
    if org is None:
        return _to_login()
    if tab not in dict(TABS):
        tab = "pending"
    counts = {
        status: n
        for status, n in session.execute(
            select(Assessment.status, func.count())
            .where(Assessment.organisation_id == org.id)
            .group_by(Assessment.status)
        )
    }
    tab_counts = {t: sum(counts.get(s, 0) for s in QUEUE_STATUSES[t]) for t in QUEUE_STATUSES}
    alerts = list_alerts(session, org.id) if tab == "sent" else []
    tab_counts["sent"] = len(alerts) if tab == "sent" else len(list_alerts(session, org.id))
    items = [] if tab == "sent" else list_assessments(session, org.id, QUEUE_STATUSES[tab])
    return templates.TemplateResponse(
        request,
        "queue.html",
        {
            "org": org, "tab": tab, "tabs": TABS, "tab_counts": tab_counts,
            "items": items, "alerts": alerts,
            "reviewer": request.cookies.get(NAME_COOKIE, ""),
            "flash": request.query_params.get("flash"),
        },
    )


@router.post("/assessments/{assessment_id}/review")
def review(
    request: Request,
    session: SessionDep,
    assessment_id: int,
    decision: Annotated[str, Form()],
    message: Annotated[str, Form()] = "",
) -> Response:
    org = _org_from_cookie(request, session)
    if org is None:
        return _to_login()
    reviewer = request.cookies.get(NAME_COOKIE) or "unknown"
    a = session.get(Assessment, assessment_id)
    edited = decision == "approve" and a is not None and message.strip() != a.drafted_message
    req = ReviewRequest(
        decision="edit" if edited else decision,
        reviewer=reviewer,
        edited_message=message.strip() if edited else None,
    )
    try:
        _, n = apply_review(session, org, assessment_id, req, DefaultNotifier())
    except ReviewError as exc:
        return RedirectResponse(f"/ui?flash={quote(exc.detail)}", status_code=303)
    if n is None:
        flash = "Rejected. Nothing was sent."
    elif n.status == "sent":
        flash = f"Sent via {n.channel}."
    elif n.status == "skipped_duplicate":
        flash = "Approved. Not re-sent: the traveller already has this alert."
    else:
        flash = f"Approved, but delivery failed: {n.error}"
    return RedirectResponse(f"/ui?flash={quote(flash)}", status_code=303)
