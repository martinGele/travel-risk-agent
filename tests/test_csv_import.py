from datetime import date

import pytest

from travel_risk.cli import demo_csv
from travel_risk.trips.csv_import import parse_csv, parse_date

TODAY = date(2026, 11, 17)


@pytest.mark.parametrize(
    ("raw", "expected", "ambiguous"),
    [
        ("2026-11-20", date(2026, 11, 20), False),
        ("2026-11-20T09:00:00", date(2026, 11, 20), False),
        ("20/11/2026", date(2026, 11, 20), False),  # day > 12: unambiguous
        ("11/20/2026", date(2026, 11, 20), False),  # month/day, US style
        ("03/04/2026", date(2026, 4, 3), True),  # ambiguous, read day-first
        ("05/05/2026", date(2026, 5, 5), False),  # same either way
        ("20 Nov 2026", date(2026, 11, 20), False),
        ("Nov 20, 2026", date(2026, 11, 20), False),
        ("20.11.2026", date(2026, 11, 20), False),
    ],
)
def test_parse_date(raw, expected, ambiguous):
    assert parse_date(raw, day_first=True) == (expected, ambiguous)


def test_ambiguous_month_first():
    assert parse_date("03/04/2026", day_first=False) == (date(2026, 3, 4), True)


def test_bad_date():
    with pytest.raises(ValueError):
        parse_date("next Tuesday", day_first=True)


def test_demo_csv_accepts_good_rows_and_explains_bad_ones():
    result = parse_csv(demo_csv(TODAY), TODAY)
    assert len(result.rows) == 11
    reasons = sorted(r["reason"] for r in result.rejected)
    assert len(reasons) == 3
    assert any("missing traveller_email" in r for r in reasons)
    assert any("already ended" in r for r in reasons)
    assert any("Narnia" in r for r in reasons)
    countries = {r.country_iso for r in result.rows}
    assert {"LB", "UG", "AE", "UA", "PS", "GE"} <= countries


def test_header_aliases_semicolons_and_bom():
    data = "﻿Name;Email;Country;Start;End\nA B;a@x.io;UK;2026-12-01;2026-12-03\n".encode()
    result = parse_csv(data, TODAY)
    assert result.rejected == []
    assert result.rows[0].country_iso == "GB"


def test_missing_columns_rejects_file():
    result = parse_csv(b"name,email\nA,a@x.io\n", TODAY)
    assert result.rows == []
    assert "missing columns" in result.rejected[0]["reason"]


def test_end_before_start_rejected():
    data = b"name,email,country,start,end\nA,a@x.io,France,2026-12-05,2026-12-01\n"
    assert "before start" in parse_csv(data, TODAY).rejected[0]["reason"]


def test_ambiguous_dates_produce_warning():
    data = b"name,email,country,start,end\nA,a@x.io,France,03/12/2026,04/12/2026\n"
    result = parse_csv(data, TODAY)
    assert result.rows[0].start_date == date(2026, 12, 3)
    assert result.warnings and "line" in result.warnings[0]


@pytest.mark.parametrize(("raw", "tidy"), [
    ("beirut ", "Beirut"), ("NEW  YORK", "New York"), ("McAllen", "McAllen"),
    ("Ho Chi Minh City", "Ho Chi Minh City"), ("", None), ("   ", None),
])
def test_tidy_city(raw, tidy):
    from travel_risk.trips.csv_import import tidy_city

    assert tidy_city(raw) == tidy
