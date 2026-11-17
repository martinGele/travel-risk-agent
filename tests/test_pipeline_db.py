"""Trip import -> rules -> model -> routing -> review -> notification, against real PostgreSQL."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from travel_risk.api.auth import hash_key
from travel_risk.api.main import app, get_notifier, get_trip_assessor
from travel_risk.assess.pipeline import assess_advisory_change, assess_new_trips, load_trips
from travel_risk.assess.review import ReviewError, apply_review
from travel_risk.db import get_session
from travel_risk.ingestion.service import store_snapshots
from travel_risk.ingestion.snapshot import AdvisorySnapshot, Source
from travel_risk.llm.base import ModelError
from travel_risk.llm.heuristic import HeuristicRiskModel
from travel_risk.models import Advisory, Assessment, Notification, Organisation
from travel_risk.notify.notifier import DeliveryResult
from travel_risk.schemas import ReviewRequest
from travel_risk.trips.csv_import import import_trips, parse_csv

pytestmark = pytest.mark.db
TODAY = date.today()
T0 = datetime(2026, 11, 1, tzinfo=UTC)


class CountingModel(HeuristicRiskModel):
    def __init__(self, fail: bool = False):
        self.calls = 0
        self.fail = fail

    def assess(self, item):
        self.calls += 1
        if self.fail:
            raise ModelError("boom")
        return super().assess(item)


class RecordingNotifier:
    def __init__(self):
        self.sent = []

    def deliver(self, d):
        self.sent.append(d)
        return DeliveryResult(True)


def adv(source, iso, level, regional=False, summary="Advisory text.", updated=T0, statuses=()):
    return AdvisorySnapshot(
        source=source, country_iso=iso, level=level, source_level_label=f"Level {level}",
        regional=regional, title=f"{iso} advice", summary=summary, url=f"https://x/{iso}",
        published_at=T0, source_updated_at=updated, alert_status=tuple(statuses),
    )


def make_org(session, name="Acme", key="key-acme"):
    org = Organisation(name=name, contact_email=f"t@{name}.example", api_key_hash=hash_key(key))
    session.add(org)
    session.flush()
    return org


def csv_rows(*rows):
    head = "name,email,country,city,start,end\n"
    return (head + "\n".join(rows) + "\n").encode()


def d(days):
    return (TODAY + timedelta(days=days)).isoformat()


@pytest.fixture
def world(session):
    store_snapshots(session, Source.US_STATE, [adv(Source.US_STATE, "LB", 4),
                                               adv(Source.US_STATE, "JP", 1)])
    store_snapshots(session, Source.UK_FCDO, [adv(Source.UK_FCDO, "LB", 3, regional=True)])
    org = make_org(session)
    parsed = parse_csv(csv_rows(
        f"Ana P,ana@acme.example,Lebanon,Beirut,{d(3)},{d(8)}",
        f"Dan C,dan@acme.example,LB,beirut,{d(3)},{d(8)}",  # same group as Ana
        f"Ken M,ken@acme.example,Japan,Tokyo,{d(5)},{d(9)}",  # level 1: no assessment
    ), TODAY)
    outcome = import_trips(session, org.id, parsed)
    return org, load_trips(session, [t.id for t in outcome.created])


def test_new_trips_grouped_routed_and_idempotent(session, world):
    org, trips = world
    model = CountingModel()
    created = assess_new_trips(session, trips, model, TODAY)
    # 2 Beirut trips x 2 sources; Tokyo never reaches the model.
    assert len(created) == 4
    assert model.calls == 2  # one call per (advisory, city, dates) group, not per traveller
    assert {a.status for a in created} == {"pending"}
    assert all("high_level" in a.route_reasons for a in created)
    assert all("@" not in a.reason for a in created)
    assert "Hi Ana" in next(a.drafted_message for a in created if a.trip_id == trips[0].id)

    assert assess_new_trips(session, trips, model, TODAY) == []  # re-run creates nothing


def test_model_failure_becomes_review_item(session, world):
    _, trips = world
    created = assess_new_trips(session, trips[:1], CountingModel(fail=True), TODAY)
    assert created and all(a.status == "pending" for a in created)
    assert all("model_error" in a.route_reasons and a.confidence == 0 for a in created)


def test_advisory_update_supersedes_open_assessments(session, world):
    _, trips = world
    first = assess_new_trips(session, trips, CountingModel(), TODAY)
    uk_ids = {a.id for a in first if session.get(Advisory, a.advisory_id).source == "uk_fcdo"}
    _, _, triggering = store_snapshots(
        session, Source.UK_FCDO,
        [adv(Source.UK_FCDO, "LB", 4, statuses=("avoid_all_travel_to_whole_country",))],
    )
    assert triggering[0].change_kind == "level_up"
    new = assess_advisory_change(session, triggering[0], CountingModel(), TODAY)
    assert len(new) == 2
    session.flush()
    superseded = session.scalars(
        select(Assessment).where(Assessment.status == "superseded")
    ).all()
    assert {s.id for s in superseded} == uk_ids  # US assessments are untouched
    assert {s.superseded_by_id for s in superseded} == {a.id for a in new}


def test_level_down_reaches_previously_notified_travellers(session, world):
    org, trips = world
    first = assess_new_trips(session, trips, CountingModel(), TODAY)
    notifier = RecordingNotifier()
    us = [a for a in first if session.get(Advisory, a.advisory_id).source == "us_state"]
    for a in us:
        apply_review(session, org, a.id, ReviewRequest(decision="approve", reviewer="M"), notifier)
    _, _, triggering = store_snapshots(session, Source.US_STATE,
                                       [adv(Source.US_STATE, "LB", 1, summary="Eased.")])
    assert triggering[0].change_kind == "level_down"
    eased = assess_advisory_change(session, triggering[0], CountingModel(), TODAY)
    assert {a.trip_id for a in eased} == {a.trip_id for a in us}
    assert all(a.advisory_id == triggering[0].id for a in eased)  # the level-1 version


def test_review_sends_once_and_is_org_scoped(session, world):
    org, trips = world
    created = assess_new_trips(session, trips, CountingModel(), TODAY)
    notifier = RecordingNotifier()
    a = created[0]

    a2, n = apply_review(session, org, a.id, ReviewRequest(decision="approve", reviewer="Mia"),
                         notifier)
    assert (a2.status, n.status, n.channel) == ("approved", "sent", "log")
    assert notifier.sent[0].message == a.drafted_message

    with pytest.raises(ReviewError) as exc:
        apply_review(session, org, a.id, ReviewRequest(decision="approve", reviewer="Mia"),
                     notifier)
    assert exc.value.status_code == 409

    other = make_org(session, "Other", "key-other")
    with pytest.raises(ReviewError) as exc:
        apply_review(session, other, created[1].id,
                     ReviewRequest(decision="reject", reviewer="X"), notifier)
    assert exc.value.status_code == 404

    _, n = apply_review(session, org, created[1].id,
                        ReviewRequest(decision="edit", reviewer="Mia", edited_message="Custom"),
                        notifier)
    assert notifier.sent[-1].message == "Custom"
    _, n = apply_review(session, org, created[2].id,
                        ReviewRequest(decision="reject", reviewer="Mia"), notifier)
    assert n is None and len(notifier.sent) == 2


def test_same_level_is_not_sent_twice(session, world):
    org, trips = world
    first = assess_new_trips(session, trips[:1], CountingModel(), TODAY)
    us = next(a for a in first if "Level 4" in a.reason)
    notifier = RecordingNotifier()
    apply_review(session, org, us.id, ReviewRequest(decision="approve", reviewer="M"), notifier)
    # Text-only change, same level: a new assessment appears but the traveller isn't re-sent.
    _, _, trig = store_snapshots(session, Source.US_STATE, [replace(
        adv(Source.US_STATE, "LB", 4), summary="New wording.",
        source_updated_at=T0 + timedelta(days=1))])
    new = assess_advisory_change(session, trig[0], CountingModel(), TODAY)
    _, n = apply_review(session, org, new[0].id,
                        ReviewRequest(decision="approve", reviewer="M"), notifier)
    assert n.status == "skipped_duplicate" and len(notifier.sent) == 1


def test_api_import_review_and_alerts(session):
    store_snapshots(session, Source.US_STATE, [adv(Source.US_STATE, "LB", 4)])
    org = make_org(session, "Api", "key-api")
    ran = []
    notifier = RecordingNotifier()

    def assessor(ids):
        ran.extend(ids)
        assess_new_trips(session, load_trips(session, ids), CountingModel(), TODAY)

    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_trip_assessor] = lambda: assessor
    app.dependency_overrides[get_notifier] = lambda: notifier
    h = {"X-API-Key": "key-api"}
    try:
        c = TestClient(app)
        body = csv_rows(f"Ana P,ana@api.example,Lebanon,Beirut,{d(3)},{d(8)}",
                        f"Bad,not-an-email,Lebanon,Beirut,{d(3)},{d(8)}")
        r = c.post(f"/v1/orgs/{org.id}/trips/import", headers=h,
                   files={"file": ("trips.csv", body, "text/csv")}).json()
        assert (r["accepted"], len(r["rejected"]), r["trips_queued_for_assessment"]) == (1, 1, 1)
        assert len(ran) == 1

        queue = c.get(f"/v1/orgs/{org.id}/assessments?status=pending", headers=h).json()
        assert len(queue) == 1 and queue[0]["traveller"]["name"] == "Ana P"
        assert c.get(f"/v1/orgs/{org.id}/assessments?status=bogus", headers=h).status_code == 422

        r = c.post(f"/v1/orgs/{org.id}/assessments/{queue[0]['id']}/review", headers=h,
                   json={"decision": "edit", "reviewer": "Mia"})
        assert r.status_code == 422  # edit without a message
        r = c.post(f"/v1/orgs/{org.id}/assessments/{queue[0]['id']}/review", headers=h,
                   json={"decision": "approve", "reviewer": "Mia"}).json()
        assert r["notification"]["status"] == "sent"
        alerts = c.get(f"/v1/orgs/{org.id}/alerts", headers=h).json()
        assert alerts[0]["reviewer"] == "Mia" and alerts[0]["traveller"] == "Ana P"
    finally:
        app.dependency_overrides.clear()


def test_review_page(session, world):
    org, trips = world
    assess_new_trips(session, trips, CountingModel(), TODAY)
    app.dependency_overrides[get_session] = lambda: session
    try:
        c = TestClient(app)
        assert c.get("/ui", follow_redirects=False).headers["location"] == "/ui/login"
        bad = c.post("/ui/login", data={"api_key": "nope", "reviewer": "Mia"},
                     follow_redirects=False)
        assert "error" in bad.headers["location"]
        c.post("/ui/login", data={"api_key": "key-acme", "reviewer": "Mia"})
        page = c.get("/ui").text
        assert "Ana P" in page and "Dan C" in page and "Ken M" not in page
        ana_trip = trips[0].id
        ids = list(session.scalars(select(Assessment.id).where(
            Assessment.trip_id == ana_trip, Assessment.status == "pending")))
        assert len(ids) == 2  # US + UK for the same trip: one card, one decision
        assert page.count('name="ids"') == 2  # Ana and Dan, not four cards
        r = c.post("/ui/trips/review",
                   data={"ids": ",".join(map(str, ids)), "decision": "approve",
                         "message": "Edited by Mia"},
                   follow_redirects=False)
        assert "Sent" in r.headers["location"]
        decided = [session.get(Assessment, i) for i in ids]
        assert {a.status for a in decided} == {"edited"}
        notes = session.scalars(select(Notification).where(
            Notification.assessment_id.in_(ids))).all()
        assert len(notes) == 1 and notes[0].status == "sent"  # one message for the trip
        # Deciding again is refused.
        r = c.post("/ui/trips/review", data={"ids": ",".join(map(str, ids)),
                                              "decision": "approve"}, follow_redirects=False)
        assert "no%20longer%20pending" in r.headers["location"]
        assert "Mia" in c.get("/ui?tab=sent").text
    finally:
        app.dependency_overrides.clear()
