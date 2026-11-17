"""UK FCDO foreign travel advice via the GOV.UK Content API (JSON)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

import httpx

from travel_risk.countries import UnknownCountry, uk_slug_to_iso2
from travel_risk.ingestion.snapshot import AdvisorySnapshot, Source, html_to_text

log = logging.getLogger(__name__)

INDEX_URL = "https://www.gov.uk/api/content/foreign-travel-advice"
COUNTRY_URL = "https://www.gov.uk/api/content/foreign-travel-advice/{slug}"

AAT_WHOLE = "avoid_all_travel_to_whole_country"
AAT_PARTS = "avoid_all_travel_to_parts"
AABE_WHOLE = "avoid_all_but_essential_travel_to_whole_country"
AABE_PARTS = "avoid_all_but_essential_travel_to_parts"

_STATUS_LEVEL = {AAT_WHOLE: 4, AAT_PARTS: 3, AABE_WHOLE: 3, AABE_PARTS: 2}
_STATUS_LABEL = {
    AAT_WHOLE: "Advise against all travel (whole country)",
    AAT_PARTS: "Advise against all travel (parts)",
    AABE_WHOLE: "Advise against all but essential travel (whole country)",
    AABE_PARTS: "Advise against all but essential travel (parts)",
}

# The pages that matter for risk; entry requirements, health etc. are left out of the summary.
RISK_PARTS = ("warnings-and-insurance", "safety-and-security", "terrorism")


@dataclass(frozen=True)
class IndexEntry:
    slug: str
    name: str
    country_iso: str
    public_updated_at: datetime
    change_description: str
    api_url: str


def parse_index(data: dict) -> list[IndexEntry]:
    out: list[IndexEntry] = []
    for child in data.get("links", {}).get("children", []):
        country = child["details"]["country"]
        try:
            iso = uk_slug_to_iso2(country["slug"], country.get("name"))
        except UnknownCountry as exc:
            log.warning("skipping UK index entry: %s", exc)
            continue
        out.append(
            IndexEntry(
                slug=country["slug"],
                name=country["name"],
                country_iso=iso,
                public_updated_at=_dt(child["public_updated_at"]),
                change_description=child["details"].get("change_description", "") or "",
                api_url=child["api_url"],
            )
        )
    return out


def level_from_alert_status(statuses: list[str] | tuple[str, ...]) -> tuple[int, bool, str]:
    """Return (normalised level, regional flag, label). See docs/MATCHING_RULES.md §1."""
    known = [s for s in statuses if s in _STATUS_LEVEL]
    unknown = set(statuses) - set(known)
    if unknown:
        log.warning("unknown FCDO alert_status values: %s", sorted(unknown))
    if not known:
        return 1, False, "No FCDO travel warnings"
    top = max(known, key=lambda s: _STATUS_LEVEL[s])
    level = _STATUS_LEVEL[top]
    # Regional if the strictest advice applies only to parts of the country.
    regional = top.endswith("_to_parts")
    return level, regional, _STATUS_LABEL[top]


def parse_country(data: dict) -> AdvisorySnapshot:
    details = data["details"]
    country = details["country"]
    iso = uk_slug_to_iso2(country["slug"], country.get("name"))
    statuses = tuple(sorted(details.get("alert_status") or []))
    level, regional, label = level_from_alert_status(statuses)

    parts = {p["slug"]: p for p in details.get("parts", [])}
    sections = [
        f"## {parts[slug]['title']}\n{html_to_text(parts[slug]['body'])}"
        for slug in RISK_PARTS
        if slug in parts
    ]

    return AdvisorySnapshot(
        source=Source.UK_FCDO,
        country_iso=iso,
        level=level,
        source_level_label=label,
        regional=regional,
        title=data.get("title", f"{country['name']} travel advice"),
        summary="\n\n".join(sections),
        url=data.get("web_url") or f"https://www.gov.uk/foreign-travel-advice/{country['slug']}",
        published_at=_dt(data["first_published_at"]) if data.get("first_published_at") else None,
        source_updated_at=_dt(data["public_updated_at"]),
        source_edited_at=_dt(data["updated_at"]) if data.get("updated_at") else None,
        change_description=details.get("change_description"),
        alert_status=statuses,
    )


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def fetch_index(client: httpx.Client) -> list[IndexEntry]:
    resp = client.get(INDEX_URL)
    resp.raise_for_status()
    return parse_index(resp.json())


def fetch_country(client: httpx.Client, slug: str) -> AdvisorySnapshot:
    resp = client.get(COUNTRY_URL.format(slug=slug))
    resp.raise_for_status()
    return parse_country(resp.json())
