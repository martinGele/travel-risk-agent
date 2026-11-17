"""Email, digest, MCP server and maintenance endpoints."""

import asyncio
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.test_pipeline_db import RecordingNotifier, csv_rows, d, make_org
from tests.test_pipeline_db import adv as make_adv
from travel_risk import mcp_server
from travel_risk.api.main import app, get_notifier
from travel_risk.assess.pipeline import assess_new_trips, load_trips
from travel_risk.db import get_session
from travel_risk.ingestion.service import store_snapshots
from travel_risk.ingestion.snapshot import Source
from travel_risk.llm.heuristic import HeuristicRiskModel
from travel_risk.models import Assessment, Notification, Trip
from travel_risk.notify.digest import send_digests
from travel_risk.notify.notifier import DefaultNotifier, Delivery
from travel_risk.trips.csv_import import import_trips, parse_csv

TODAY = date.today()


def test_email_uses_ses(monkeypatch):
    from travel_risk.config import get_settings

    monkeypatch.setattr(get_settings(), "ses_from_email", "alerts@acme.example")
    calls = []
    ses = SimpleNamespace(send_email=lambda **kw: calls.append(kw))
    result = DefaultNotifier(ses=ses).deliver(
        Delivery(notification_id=1, channel="email", message="Hi", email_to="a@acme.example"))
    assert result.ok
    assert calls[0]["Destination"] == {"ToAddresses": ["a@acme.example"]}
    assert calls[0]["Content"]["Simple"]["Body"]["Text"]["Data"] == "Hi"


def test_email_failure_keeps_details_out_of_error(monkeypatch):
    from travel_risk.config import get_settings

    monkeypatch.setattr(get_settings(), "ses_from_email", "alerts@acme.example")

    def boom(**kw):
        raise RuntimeError("MessageRejected: a@acme.example not verified")

    result = DefaultNotifier(ses=SimpleNamespace(send_email=boom)).deliver(
        Delivery(notification_id=1, channel="email", message="Hi", email_to="a@acme.example"))
    assert not result.ok and "acme" not in result.error


@pytest.fixture
def lowlevel(session):
    store_snapshots(session, Source.US_STATE, [make_adv(Source.US_STATE, "FR", 2),
                                               make_adv(Source.US_STATE, "LB", 4)])
    org = make_org(session, "Digest", "key-digest")
    out = import_trips(session, org.id, parse_csv(csv_rows(
        f"Lena F,lena@d.example,France,Paris,{d(5)},{d(7)}",
        f"Ana P,ana@d.example,Lebanon,Beirut,{d(3)},{d(8)}",
    ), TODAY))
    assess_new_trips(session, load_trips(session, [t.id for t in out.created]),
                     HeuristicRiskModel(), TODAY)
    return org


@pytest.mark.db
def test_digest_goes_to_manager_once(session, lowlevel):
    notifier = RecordingNotifier()
    assert send_digests(session, notifier, TODAY) == {lowlevel.id: 1}
    msg = notifier.sent[0]
    assert msg.email_to == lowlevel.contact_email and "Lena F" in msg.message
    assert "Ana P" not in msg.message  # high severity goes through review, not the digest
    statuses = set(session.scalars(select(Assessment.status).where(
        Assessment.organisation_id == lowlevel.id)))
    assert "digested" in statuses
    assert send_digests(session, notifier, TODAY) == {}  # nothing left to send


@pytest.mark.db
def test_mcp_tools(session, lowlevel):
    affected = mcp_server.who_is_affected(session, lowlevel.id, "Lebanon", 14, TODAY)
    assert [a["traveller"] for a in affected] == ["Ana P"]
    assert affected[0]["severity"] == "high"
    assert mcp_server.who_is_affected(session, lowlevel.id, None, 1, TODAY) == []  # too far
    assert len(mcp_server.review_queue(session, lowlevel.id)) == 1
    assert mcp_server.current_advisories(session, "lb")[0]["level"] == 4
    assert {t["traveller"] for t in mcp_server.upcoming_trips(
        session, lowlevel.id, None, 30, TODAY)} == {"Lena F", "Ana P"}
    other = make_org(session, "Other", "key-other2")
    assert mcp_server.who_is_affected(session, other.id, None, 30, TODAY) == []
    with pytest.raises(ValueError, match="Unknown country"):
        mcp_server.who_is_affected(session, lowlevel.id, "Narnia", 14, TODAY)


def test_mcp_tools_are_read_only():
    server = mcp_server.build_server(org_id=1)
    tools = asyncio.run(server.list_tools())
    names = {t.name for t in tools}
    assert names == {"get_affected_travellers", "get_review_queue",
                     "get_current_advisories", "get_upcoming_trips"}
    assert all(t.annotations.read_only_hint for t in tools)
    assert not any(t.annotations.destructive_hint for t in tools)
    assert not any(w in n for n in names for w in ("send", "approve", "reject", "delete"))


@pytest.mark.db
def test_operator_endpoints(session, lowlevel):
    old = session.scalars(select(Trip).where(Trip.organisation_id == lowlevel.id,
                                             Trip.city == "Beirut")).one()
    old.start_date, old.end_date = TODAY - timedelta(days=60), TODAY - timedelta(days=40)
    session.flush()
    notifier = RecordingNotifier()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_notifier] = lambda: notifier
    try:
        c = TestClient(app)
        assert c.post("/v1/maintenance/purge").status_code == 401
        from travel_risk.config import get_settings

        h = {"X-API-Key": get_settings().operator_api_key.get_secret_value()}
        assert c.post("/v1/maintenance/purge", headers=h).json()["deleted_trips"] == 1
        assert c.post("/v1/digests/send", headers=h).json() == {"organisations": 1, "items": 1}
        assert session.scalars(select(Notification)).first().channel == "log"
    finally:
        app.dependency_overrides.clear()
