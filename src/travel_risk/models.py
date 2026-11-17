"""ORM tables. Rationale per field: docs/DATA_MODEL.md."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _now() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Advisory(Base):
    """One row per *version* of a (source, country) advisory."""

    __tablename__ = "advisories"
    __table_args__ = (
        UniqueConstraint("source", "country_iso", "version"),
        Index("ix_advisories_current", "country_iso", "source", postgresql_where="is_current"),
        CheckConstraint("level BETWEEN 1 AND 4", name="level_range"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(16))
    country_iso: Mapped[str] = mapped_column(String(2), index=True)
    version: Mapped[int] = mapped_column(Integer)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    level: Mapped[int] = mapped_column(Integer)
    source_level_label: Mapped[str] = mapped_column(String(128))
    regional: Mapped[bool] = mapped_column(Boolean)
    alert_status: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    title: Mapped[str] = mapped_column(String(512))
    summary: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(String(1024))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    change_description: Mapped[str | None] = mapped_column(Text)
    change_kind: Mapped[str] = mapped_column(String(16))
    triggers_assessment: Mapped[bool] = mapped_column(Boolean)
    content_hash: Mapped[str] = mapped_column(String(64))
    fetched_at: Mapped[datetime] = _now()


class Organisation(Base):
    __tablename__ = "organisations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(256))
    contact_email: Mapped[str] = mapped_column(String(320))
    notify_channel: Mapped[str] = mapped_column(String(16), default="email")  # email | slack
    slack_webhook_url: Mapped[str | None] = mapped_column(String(1024))
    api_key_hash: Mapped[str] = mapped_column(String(64), unique=True)  # sha256 of the key
    created_at: Mapped[datetime] = _now()


class Traveller(Base):
    __tablename__ = "travellers"
    __table_args__ = (UniqueConstraint("organisation_id", "email"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    organisation_id: Mapped[int] = mapped_column(
        ForeignKey("organisations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(256))
    email: Mapped[str] = mapped_column(String(320))
    slack_id: Mapped[str | None] = mapped_column(String(64))


class Trip(Base):
    __tablename__ = "trips"
    __table_args__ = (
        CheckConstraint("end_date >= start_date", name="dates_ordered"),
        Index("ix_trips_match", "country_iso", "end_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # Denormalised from traveller so every query can filter by organisation directly.
    organisation_id: Mapped[int] = mapped_column(
        ForeignKey("organisations.id", ondelete="CASCADE"), index=True
    )
    traveller_id: Mapped[int] = mapped_column(ForeignKey("travellers.id", ondelete="CASCADE"))
    country_iso: Mapped[str] = mapped_column(String(2))
    city: Mapped[str | None] = mapped_column(String(256))
    city_normalised: Mapped[str] = mapped_column(String(256), default="")
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(16), default="csv")  # csv | calendar
    external_ref: Mapped[str | None] = mapped_column(String(256))
    created_at: Mapped[datetime] = _now()

    traveller: Mapped[Traveller] = relationship()


class Assessment(Base):
    __tablename__ = "assessments"
    __table_args__ = (
        Index("ix_assessments_queue", "organisation_id", "status"),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence_range"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organisation_id: Mapped[int] = mapped_column(
        ForeignKey("organisations.id", ondelete="CASCADE")
    )
    trip_id: Mapped[int] = mapped_column(ForeignKey("trips.id", ondelete="CASCADE"), index=True)
    advisory_id: Mapped[int] = mapped_column(ForeignKey("advisories.id"))
    group_key: Mapped[str] = mapped_column(String(512), index=True)
    affected: Mapped[bool] = mapped_column(Boolean)
    severity: Mapped[str] = mapped_column(String(8))
    reason: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    drafted_message: Mapped[str] = mapped_column(Text)
    route: Mapped[str] = mapped_column(String(16))  # review | digest | no_action
    route_reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    # pending | approved | edited | rejected | superseded | digested | no_action
    status: Mapped[str] = mapped_column(String(16))
    superseded_by_id: Mapped[int | None] = mapped_column(ForeignKey("assessments.id"))
    model: Mapped[str] = mapped_column(String(128))
    prompt_version: Mapped[str] = mapped_column(String(32))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    trace_id: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = _now()


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    assessment_id: Mapped[int] = mapped_column(
        ForeignKey("assessments.id", ondelete="CASCADE"), index=True
    )
    decision: Mapped[str] = mapped_column(String(8))  # approve | edit | reject
    edited_message: Mapped[str | None] = mapped_column(Text)
    reviewer: Mapped[str] = mapped_column(String(256))
    decided_at: Mapped[datetime] = _now()


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    organisation_id: Mapped[int] = mapped_column(
        ForeignKey("organisations.id", ondelete="CASCADE"), index=True
    )
    assessment_id: Mapped[int] = mapped_column(ForeignKey("assessments.id", ondelete="CASCADE"))
    review_id: Mapped[int | None] = mapped_column(ForeignKey("reviews.id"))  # null for digest
    channel: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))  # queued | sent | failed
    error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()


class SyncRun(Base):
    __tablename__ = "sync_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(16))
    started_at: Mapped[datetime] = _now()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    items_seen: Mapped[int] = mapped_column(Integer, default=0)
    versions_created: Mapped[int] = mapped_column(Integer, default=0)
    material_changes: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
