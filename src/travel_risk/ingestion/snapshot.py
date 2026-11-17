"""Source-independent representation of one advisory as fetched."""

from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class Source(StrEnum):
    US_STATE = "us_state"
    UK_FCDO = "uk_fcdo"


@dataclass(frozen=True)
class AdvisorySnapshot:
    source: Source
    country_iso: str
    level: int  # normalised 1-4, see docs/MATCHING_RULES.md §1
    source_level_label: str  # what the source actually said
    regional: bool
    title: str
    summary: str  # plain text, HTML stripped
    url: str
    published_at: datetime | None
    # When the source says the advice last changed *publicly* (UK public_updated_at, US pubDate).
    source_updated_at: datetime | None
    # UK only: moves on any edit, including non-public ones. Used to classify 'minor'.
    source_edited_at: datetime | None = None
    change_description: str | None = None
    alert_status: tuple[str, ...] = field(default_factory=tuple)

    @property
    def content_hash(self) -> str:
        payload = "\x1f".join(
            [self.source, self.country_iso, str(self.level), str(self.regional),
             ",".join(self.alert_status), self.title, self.summary]
        )
        return hashlib.sha256(payload.encode()).hexdigest()


_BLOCK_TAGS = re.compile(r"</?(p|br|li|ul|ol|h[1-6]|div|tr)\b[^>]*>", re.I)
_TAGS = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"[ \t ]+")
_BLANK_LINES = re.compile(r"\n\s*\n+")


def html_to_text(raw: str) -> str:
    """Strip HTML to readable plain text, keeping paragraph breaks."""
    text = _BLOCK_TAGS.sub("\n", raw)
    text = _TAGS.sub("", text)
    text = html.unescape(text)
    text = _SPACES.sub(" ", text)
    lines = [line.strip() for line in text.split("\n")]
    return _BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()
