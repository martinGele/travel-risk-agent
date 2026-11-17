"""Decide whether a newly fetched advisory version is worth acting on.

Contract: docs/MATCHING_RULES.md §3.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from travel_risk.ingestion.snapshot import AdvisorySnapshot, Source


class ChangeKind(StrEnum):
    NEW = "new"
    LEVEL_UP = "level_up"
    LEVEL_DOWN = "level_down"
    SCOPE_CHANGE = "scope_change"
    CONTENT_CHANGE = "content_change"
    MINOR = "minor"
    UNCHANGED = "unchanged"  # identical to the stored version: don't even store it


class StoredVersion(Protocol):
    """The fields of the latest stored version we compare against (an ORM row works)."""

    level: int
    regional: bool
    alert_status: list[str] | tuple[str, ...]
    content_hash: str
    source_updated_at: object


@dataclass(frozen=True)
class Verdict:
    kind: ChangeKind
    triggers_assessment: bool
    store: bool


def classify(new: AdvisorySnapshot, previous: StoredVersion | None) -> Verdict:
    if previous is None:
        return Verdict(ChangeKind.NEW, triggers_assessment=new.level >= 2, store=True)

    if new.level > previous.level:
        return Verdict(ChangeKind.LEVEL_UP, True, True)
    if new.level < previous.level:
        return Verdict(ChangeKind.LEVEL_DOWN, True, True)

    if new.regional != previous.regional or tuple(new.alert_status) != tuple(
        previous.alert_status or ()
    ):
        return Verdict(ChangeKind.SCOPE_CHANGE, True, True)

    hash_changed = new.content_hash != previous.content_hash
    public_date_moved = new.source_updated_at != previous.source_updated_at

    if not hash_changed:
        if public_date_moved:
            # US "reissued with no changes", or UK touched the date only.
            return Verdict(ChangeKind.MINOR, False, True)
        return Verdict(ChangeKind.UNCHANGED, False, False)

    # Text changed. For the UK, FCDO itself says whether an edit is public via public_updated_at.
    if new.source is Source.UK_FCDO and not public_date_moved:
        return Verdict(ChangeKind.MINOR, False, True)

    return Verdict(ChangeKind.CONTENT_CHANGE, triggers_assessment=new.level >= 2, store=True)
