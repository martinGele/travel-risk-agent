"""US State Department travel advisories (RSS 2.0)."""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx

from travel_risk.countries import (
    US_FIPS_FALLBACK,
    US_FIPS_IGNORED,
    UnknownCountry,
    us_slug_to_iso2,
)
from travel_risk.ingestion.snapshot import AdvisorySnapshot, Source, html_to_text

log = logging.getLogger(__name__)

FEED_URL = "https://travel.state.gov/_res/rss/TAsTWs.xml"

_LEVEL = re.compile(r"Level\s+([1-4])\s*:\s*([^<\n]+)", re.I)
_SLUG = re.compile(r"destination\.([a-z0-9]+)\.html", re.I)
# A stricter area inside a milder country, e.g. "Do Not Travel to: ..." in a Level 2 advisory.
_REGIONAL_HINT = re.compile(r"do not travel to\b|level 4", re.I)


class _Ignored(Exception):
    pass


def parse_feed(xml_text: str | bytes) -> list[AdvisorySnapshot]:
    """Parse the feed. Items that can't be mapped are logged and skipped, never fatal."""
    root = ET.fromstring(xml_text)
    out: list[AdvisorySnapshot] = []
    for item in root.iter("item"):
        try:
            out.append(_parse_item(item))
        except _Ignored as exc:
            log.debug("ignoring US advisory: %s", exc)
        except (UnknownCountry, ValueError) as exc:
            title = item.findtext("title", default="?")
            log.warning("skipping US advisory %r: %s", title, exc)
    return out


def _parse_item(item: ET.Element) -> AdvisorySnapshot:
    title = (item.findtext("title") or "").strip()
    link = (item.findtext("link") or item.findtext("guid") or "").strip()

    fips = next(
        (c.text.strip() for c in item.findall("category")
         if c.get("domain") == "Country-Tag" and c.text),
        None,
    )
    slug_match = _SLUG.search(link)
    if slug_match:
        country_iso = us_slug_to_iso2(slug_match.group(1))
    elif fips in US_FIPS_IGNORED:
        raise _Ignored(f"legacy aggregate entry {fips}")
    elif fips in US_FIPS_FALLBACK:
        country_iso = US_FIPS_FALLBACK[fips]
    else:
        raise ValueError(f"no destination slug in link {link!r} and unmapped FIPS {fips!r}")

    level_label = ""
    for cat in item.findall("category"):
        if cat.get("domain") == "Threat-Level" and cat.text:
            level_label = cat.text.strip()
    level_match = _LEVEL.search(level_label) or _LEVEL.search(title)
    if not level_match:
        raise ValueError(f"no level in {title!r}")
    level = int(level_match.group(1))
    level_label = f"Level {level}: {level_match.group(2).strip()}"

    summary = html_to_text(item.findtext("description") or "")
    regional = level < 4 and bool(_REGIONAL_HINT.search(summary))

    pub = item.findtext("pubDate")
    published = _parse_date(pub) if pub else None

    return AdvisorySnapshot(
        source=Source.US_STATE,
        country_iso=country_iso,
        level=level,
        source_level_label=level_label,
        regional=regional,
        title=title,
        summary=summary,
        url=link,
        published_at=published,
        source_updated_at=published,
    )


def _parse_date(value: str) -> datetime:
    value = value.strip()
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        # The feed uses date-only values like "Fri, 23 Oct 2026".
        dt = datetime.strptime(value, "%a, %d %b %Y")
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def fetch(client: httpx.Client) -> list[AdvisorySnapshot]:
    resp = client.get(FEED_URL)
    resp.raise_for_status()
    return parse_feed(resp.content)
