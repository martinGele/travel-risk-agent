"""Turn an assessment into the message a traveller receives. Names are added here, never sent to
the model."""

from __future__ import annotations

from datetime import date

import pycountry

SOURCE_NAMES = {"us_state": "US State Department", "uk_fcdo": "UK FCDO"}


def country_name(iso: str) -> str:
    if iso == "XK":
        return "Kosovo"
    c = pycountry.countries.get(alpha_2=iso)
    return getattr(c, "common_name", None) or (c.name if c else iso)


def format_dates(start: date, end: date) -> str:
    if start == end:
        return start.strftime("%-d %b %Y")
    if (start.year, start.month) == (end.year, end.month):
        return f"{start.day}–{end.strftime('%-d %b %Y')}"
    if start.year == end.year:
        return f"{start.strftime('%-d %b')} – {end.strftime('%-d %b %Y')}"
    return f"{start.strftime('%-d %b %Y')} – {end.strftime('%-d %b %Y')}"


def draft_message(
    *,
    traveller_name: str,
    org_name: str,
    city: str | None,
    country_iso: str,
    start: date,
    end: date,
    source: str,
    advisory_url: str,
    reason: str,
    action: str,
) -> str:
    first = traveller_name.split()[0] if traveller_name.strip() else "there"
    place = f"{city}, {country_name(country_iso)}" if city else country_name(country_iso)
    return (
        f"Hi {first},\n\n"
        f"There is a travel advisory update for your trip to {place} "
        f"({format_dates(start, end)}).\n\n"
        f"{reason}\n\n"
        f"What to do: {action}\n\n"
        f"Source: {SOURCE_NAMES.get(source, source)}: {advisory_url}\n\n"
        f"{org_name} travel team"
    )
