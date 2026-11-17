from dataclasses import replace
from datetime import UTC, datetime

import pytest

from travel_risk.ingestion.materiality import ChangeKind, classify
from travel_risk.ingestion.snapshot import AdvisorySnapshot, Source

T0 = datetime(2026, 11, 1, tzinfo=UTC)
T1 = datetime(2026, 11, 10, tzinfo=UTC)


def snap(source=Source.US_STATE, level=2, regional=False, summary="text", updated=T0,
         alert_status=()) -> AdvisorySnapshot:
    return AdvisorySnapshot(
        source=source, country_iso="LB", level=level, source_level_label=f"L{level}",
        regional=regional, title="Lebanon", summary=summary, url="https://x",
        published_at=T0, source_updated_at=updated, alert_status=tuple(alert_status),
    )


class Stored:
    """Stand-in for an ORM row."""

    def __init__(self, s: AdvisorySnapshot):
        self.level, self.regional = s.level, s.regional
        self.alert_status = list(s.alert_status)
        self.content_hash, self.source_updated_at = s.content_hash, s.source_updated_at


@pytest.mark.parametrize(("level", "triggers"), [(1, False), (2, True), (4, True)])
def test_new(level, triggers):
    v = classify(snap(level=level), None)
    assert (v.kind, v.triggers_assessment, v.store) == (ChangeKind.NEW, triggers, True)


def test_identical_is_not_stored():
    s = snap()
    v = classify(s, Stored(s))
    assert (v.kind, v.store, v.triggers_assessment) == (ChangeKind.UNCHANGED, False, False)


def test_us_reissue_with_no_changes_is_minor():
    v = classify(snap(updated=T1), Stored(snap(updated=T0)))
    assert (v.kind, v.store, v.triggers_assessment) == (ChangeKind.MINOR, True, False)


def test_level_up_and_down_trigger():
    assert classify(snap(level=3), Stored(snap(level=2))).kind is ChangeKind.LEVEL_UP
    down = classify(snap(level=2), Stored(snap(level=4)))
    assert down.kind is ChangeKind.LEVEL_DOWN and down.triggers_assessment


def test_scope_change_triggers():
    v = classify(snap(regional=True), Stored(snap(regional=False)))
    assert v.kind is ChangeKind.SCOPE_CHANGE and v.triggers_assessment


def test_uk_status_set_change_is_scope_change():
    old = snap(Source.UK_FCDO, 3, True, alert_status=["avoid_all_travel_to_parts"])
    new = snap(Source.UK_FCDO, 3, True, alert_status=[
        "avoid_all_but_essential_travel_to_parts", "avoid_all_travel_to_parts"])
    assert classify(new, Stored(old)).kind is ChangeKind.SCOPE_CHANGE


def test_content_change_triggers_only_above_level_1():
    assert classify(snap(level=2, summary="new", updated=T1),
                    Stored(snap(level=2))).triggers_assessment
    v = classify(snap(level=1, summary="new", updated=T1), Stored(snap(level=1)))
    assert v.kind is ChangeKind.CONTENT_CHANGE and not v.triggers_assessment


def test_uk_text_edit_without_public_date_is_minor():
    old = snap(Source.UK_FCDO, level=3)
    new = replace(old, summary="typo fixed")
    v = classify(new, Stored(old))
    assert (v.kind, v.triggers_assessment, v.store) == (ChangeKind.MINOR, False, True)


def test_uk_public_text_edit_is_content_change():
    old = snap(Source.UK_FCDO, level=3)
    new = replace(old, summary="new threat", source_updated_at=T1)
    assert classify(new, Stored(old)).kind is ChangeKind.CONTENT_CHANGE
