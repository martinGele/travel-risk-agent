"""Database tests. Run with: docker compose up -d db && uv run pytest -m db"""

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.conftest import load_uk
from travel_risk.api.auth import hash_key
from travel_risk.api.main import app
from travel_risk.db import get_session
from travel_risk.ingestion import uk_fcdo, us_state
from travel_risk.ingestion.service import store_snapshots
from travel_risk.ingestion.snapshot import Source
from travel_risk.models import Advisory, Organisation

pytestmark = pytest.mark.db


def test_us_feed_stores_one_current_version_per_country(session, us_feed_xml):
    snaps = us_state.parse_feed(us_feed_xml)
    seen, created, triggering = store_snapshots(session, Source.US_STATE, snaps)
    countries = {s.country_iso for s in snaps}
    assert seen == len(snaps)
    assert created == len(countries)  # Gaza+West Bank and Bonaire+Saba collapse
    assert all(a.level >= 2 for a in triggering)
    ps = session.scalars(select(Advisory).where(Advisory.country_iso == "PS")).one()
    assert ps.level == 4 and ps.regional  # strictest level; levels differ so it's regional
    assert "Gaza" in ps.summary and "West Bank" in ps.summary  # both texts kept

    # Second identical sync stores nothing.
    assert store_snapshots(session, Source.US_STATE, snaps)[1:] == (0, [])


def test_new_version_supersedes_current(session):
    v1 = uk_fcdo.parse_country(load_uk("lebanon"))
    store_snapshots(session, Source.UK_FCDO, [v1])
    v2 = replace(v1, alert_status=("avoid_all_travel_to_whole_country",), level=4, regional=False)
    _, created, triggering = store_snapshots(session, Source.UK_FCDO, [v2])
    assert created == 1 and triggering[0].change_kind == "level_up"
    rows = session.scalars(
        select(Advisory).where(Advisory.country_iso == "LB").order_by(Advisory.version)
    ).all()
    assert [(r.version, r.is_current) for r in rows] == [(1, False), (2, True)]


def test_org_routes_require_matching_key(session):
    a = Organisation(name="A", contact_email="a@x", api_key_hash=hash_key("key-a"))
    b = Organisation(name="B", contact_email="b@x", api_key_hash=hash_key("key-b"))
    session.add_all([a, b])
    session.flush()
    app.dependency_overrides[get_session] = lambda: session
    try:
        client = TestClient(app)
        url = f"/v1/orgs/{a.id}/alerts"
        assert client.get(url).status_code == 401
        assert client.get(url, headers={"X-API-Key": "key-b"}).status_code == 404
        assert client.get(url, headers={"X-API-Key": "nope"}).status_code == 404
        assert client.get(url, headers={"X-API-Key": "key-a"}).json() == []
        assert client.post("/v1/advisories/sync").status_code == 401
    finally:
        app.dependency_overrides.clear()
