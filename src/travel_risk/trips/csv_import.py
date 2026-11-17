"""Clean a customer's trip CSV. Every bad row is rejected with a reason; nothing is silently fixed.

Parsing is pure (no database) so it can be tested row by row. `import_trips` then upserts.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from travel_risk.countries import UnknownCountry, to_iso2
from travel_risk.matching.rules import normalise_city
from travel_risk.models import Traveller, Trip

# Header aliases customers actually use -> canonical column.
HEADER_ALIASES: dict[str, str] = {
    "name": "traveller_name", "traveller": "traveller_name", "employee": "traveller_name",
    "employee name": "traveller_name", "traveller name": "traveller_name",
    "email": "traveller_email", "e-mail": "traveller_email", "employee email": "traveller_email",
    "traveller email": "traveller_email",
    "country": "country", "destination country": "country", "destination": "country",
    "city": "city", "destination city": "city",
    "start": "start_date", "start date": "start_date", "from": "start_date",
    "departure": "start_date", "depart": "start_date",
    "end": "end_date", "end date": "end_date", "to": "end_date", "return": "end_date",
    "slack": "slack_id", "slack id": "slack_id",
    "ref": "external_ref", "trip id": "external_ref", "booking ref": "external_ref",
}
REQUIRED = ("traveller_name", "traveller_email", "country", "start_date", "end_date")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SLASHED = re.compile(r"^(\d{1,2})[/.](\d{1,2})[/.](\d{4})$")
_TEXT_FORMATS = ("%d %b %Y", "%d %B %Y", "%b %d %Y", "%B %d %Y", "%d-%b-%Y", "%Y/%m/%d")


@dataclass
class CleanRow:
    line: int
    traveller_name: str
    traveller_email: str
    country_iso: str
    city: str | None
    start_date: date
    end_date: date
    slack_id: str | None
    external_ref: str | None


@dataclass
class ParseResult:
    rows: list[CleanRow] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _canonical(header: str) -> str:
    key = re.sub(r"[_\s]+", " ", header.strip().lower())
    return HEADER_ALIASES.get(key, key.replace(" ", "_"))


def parse_date(raw: str, day_first: bool) -> tuple[date, bool]:
    """Return (date, was_ambiguous). Raises ValueError if unparseable."""
    value = raw.strip()
    if not value:
        raise ValueError("empty date")
    try:
        return date.fromisoformat(value[:10]), False
    except ValueError:
        pass
    if m := _SLASHED.match(value):
        a, b, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if a > 12:
            return date(year, b, a), False
        if b > 12:
            return date(year, a, b), False
        ambiguous = a != b
        return (date(year, b, a) if day_first else date(year, a, b)), ambiguous
    cleaned = value.replace(",", "")
    for fmt in _TEXT_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).date(), False
        except ValueError:
            continue
    raise ValueError(f"unrecognised date {raw!r}")


def parse_csv(data: bytes, today: date, day_first: bool = True) -> ParseResult:
    result = ParseResult()
    text = data.decode("utf-8-sig", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    try:
        header = [_canonical(h) for h in next(reader)]
    except StopIteration:
        result.rejected.append({"line": 1, "reason": "file is empty"})
        return result
    missing = [c for c in REQUIRED if c not in header]
    if missing:
        result.rejected.append({"line": 1, "reason": f"missing columns: {', '.join(missing)}"})
        return result

    ambiguous_lines: list[int] = []
    for line_no, values in enumerate(reader, start=2):
        if not any(v.strip() for v in values):
            continue
        row = {header[i]: v.strip() for i, v in enumerate(values) if i < len(header)}
        try:
            clean, ambiguous = _clean(row, line_no, today, day_first)
        except ValueError as exc:
            result.rejected.append({"line": line_no, "reason": str(exc), "row": row})
            continue
        if ambiguous:
            ambiguous_lines.append(line_no)
        result.rows.append(clean)

    if ambiguous_lines:
        order = "day/month" if day_first else "month/day"
        result.warnings.append(
            f"ambiguous dates read as {order} on lines {ambiguous_lines[:20]}"
            + (" ..." if len(ambiguous_lines) > 20 else "")
        )
    return result


def _clean(row: dict[str, str], line: int, today: date, day_first: bool) -> tuple[CleanRow, bool]:
    for col in REQUIRED:
        if not row.get(col):
            raise ValueError(f"missing {col}")
    email = row["traveller_email"].lower()
    if not _EMAIL.match(email):
        raise ValueError(f"invalid email {row['traveller_email']!r}")
    try:
        country = to_iso2(row["country"])
    except UnknownCountry as exc:
        raise ValueError(str(exc)) from exc
    start, amb_start = parse_date(row["start_date"], day_first)
    end, amb_end = parse_date(row["end_date"], day_first)
    if end < start:
        raise ValueError(f"end date {end} is before start date {start}")
    if end < today:
        raise ValueError(f"trip already ended on {end}")
    return (
        CleanRow(
            line=line,
            traveller_name=row["traveller_name"],
            traveller_email=email,
            country_iso=country,
            city=row.get("city") or None,
            start_date=start,
            end_date=end,
            slack_id=row.get("slack_id") or None,
            external_ref=row.get("external_ref") or None,
        ),
        amb_start or amb_end,
    )


@dataclass
class ImportOutcome:
    created: list[Trip]
    duplicates: int
    parse: ParseResult


def import_trips(session: Session, organisation_id: int, parsed: ParseResult) -> ImportOutcome:
    """Upsert travellers by email and add trips that don't already exist. Caller commits."""
    travellers: dict[str, Traveller] = {
        t.email: t
        for t in session.scalars(
            select(Traveller).where(Traveller.organisation_id == organisation_id)
        )
    }
    created: list[Trip] = []
    duplicates = 0
    for row in parsed.rows:
        trav = travellers.get(row.traveller_email)
        if trav is None:
            trav = Traveller(
                organisation_id=organisation_id, name=row.traveller_name,
                email=row.traveller_email, slack_id=row.slack_id,
            )
            session.add(trav)
            session.flush()
            travellers[trav.email] = trav
        else:
            trav.name = row.traveller_name
            trav.slack_id = row.slack_id or trav.slack_id

        city_norm = normalise_city(row.city)
        exists = session.scalars(
            select(Trip.id).where(
                Trip.organisation_id == organisation_id,
                Trip.traveller_id == trav.id,
                Trip.country_iso == row.country_iso,
                Trip.city_normalised == city_norm,
                Trip.start_date == row.start_date,
                Trip.end_date == row.end_date,
            )
        ).first()
        if exists:
            duplicates += 1
            continue
        trip = Trip(
            organisation_id=organisation_id, traveller_id=trav.id,
            country_iso=row.country_iso, city=row.city, city_normalised=city_norm,
            start_date=row.start_date, end_date=row.end_date,
            source="csv", external_ref=row.external_ref,
        )
        session.add(trip)
        created.append(trip)
    session.flush()
    return ImportOutcome(created=created, duplicates=duplicates, parse=parsed)
