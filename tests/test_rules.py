from datetime import date

import pytest
from pydantic import ValidationError

from travel_risk.matching.rules import (
    Route,
    TripLike,
    group_key,
    is_candidate,
    normalise_city,
    route,
)
from travel_risk.schemas import RiskAssessment

TODAY = date(2026, 11, 17)


def trip(start=date(2026, 11, 20), end=date(2026, 11, 25), city="Beirut", country="LB"):
    return TripLike(country_iso=country, city=city, start_date=start, end_date=end)


def ra(affected=True, severity="medium", confidence=0.9) -> RiskAssessment:
    return RiskAssessment(affected=affected, severity=severity, reason="r", action="a",
                          confidence=confidence)


class TestCandidate:
    def test_upcoming_trip_matches(self):
        assert is_candidate(trip(), "LB", 3, TODAY)

    def test_trip_ending_today_matches(self):
        assert is_candidate(trip(start=date(2026, 11, 10), end=TODAY), "LB", 3, TODAY)

    def test_trip_ended_yesterday_does_not(self):
        assert not is_candidate(trip(start=date(2026, 11, 10), end=date(2026, 11, 16)),
                                "LB", 4, TODAY)

    def test_other_country_does_not(self):
        assert not is_candidate(trip(country="IL", city="Jerusalem"), "PS", 4, TODAY)

    def test_level_1_never_matches(self):
        assert not is_candidate(trip(), "LB", 1, TODAY)


class TestCity:
    @pytest.mark.parametrize(("a", "b"), [
        ("Kyiv", "Kiev"), ("Beirut ", "beirut"), ("São Paulo", "Sao Paulo"),
        ("Ho Chi Minh City", "Saigon"), ("Bombay", "Mumbai"),
    ])
    def test_spellings_normalise_together(self, a, b):
        assert normalise_city(a) == normalise_city(b)

    def test_group_key_merges_spellings(self):
        assert group_key(7, trip(city="Kiev", country="UA")) == group_key(
            7, trip(city="Kyiv", country="UA"))

    def test_group_key_separates_dates(self):
        assert group_key(7, trip()) != group_key(7, trip(end=date(2026, 11, 26)))


class TestRouting:
    def test_quiet_affected_case_goes_to_digest(self):
        d = route(ra(severity="low"), advisory_level=2, advisory_regional=False,
                  other_source_level=2)
        assert (d.route, d.reasons) == (Route.DIGEST, ())

    def test_unaffected_low_level_is_kept_as_no_action(self):
        d = route(ra(affected=False, severity="low"), 2, False, None)
        assert d.route is Route.NO_ACTION

    def test_llm_cannot_suppress_a_level_4(self):
        d = route(ra(affected=False, severity="low", confidence=0.99), 4, False, 4)
        assert d.route is Route.REVIEW
        assert "llm_dismissed_high" in d.reasons

    @pytest.mark.parametrize(("kwargs", "reason"), [
        ({"advisory_level": 3}, "high_level"),
        ({"advisory_regional": True}, "regional"),
        ({"other_source_level": 4}, "sources_disagree"),
        ({"assessment": ra(severity="high")}, "high_severity"),
        ({"assessment": ra(confidence=0.69)}, "low_confidence"),
    ])
    def test_each_reason_forces_review(self, kwargs, reason):
        args = {"assessment": ra(severity="low"), "advisory_level": 2,
                "advisory_regional": False, "other_source_level": 2} | kwargs
        d = route(**args)
        assert d.route is Route.REVIEW and reason in d.reasons

    def test_confidence_exactly_threshold_is_not_low(self):
        d = route(ra(severity="low", confidence=0.7), 2, False, None)
        assert d.route is Route.DIGEST


def test_rubric_unaffected_must_be_low():
    with pytest.raises(ValidationError):
        ra(affected=False, severity="high")
