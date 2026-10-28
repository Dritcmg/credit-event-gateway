from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Event(Base):
    __tablename__ = "gateway_events"
    __table_args__ = (
        UniqueConstraint("tenant_id", "event_id", name="uq_event_identity"),
        CheckConstraint("sequence > 0", name="ck_event_sequence"),
        CheckConstraint("attempts >= 0", name="ck_event_attempts"),
        CheckConstraint("status IN ('queued','processed','rejected')", name="ck_event_status"),
        Index("ix_events_work", "status", "available_at", "created_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    event_id: Mapped[str] = mapped_column(String(64))
    application_id: Mapped[str] = mapped_column(String(64))
    sequence: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JSON)
    payload_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    reason: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Application(Base):
    __tablename__ = "gateway_applications"
    __table_args__ = (
        CheckConstraint("last_sequence >= 0", name="ck_application_sequence"),
        CheckConstraint(
            "status IN ('pending','submitted','approved','declined','funded')",
            name="ck_application_status",
        ),
    )
    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    application_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    last_sequence: Mapped[int] = mapped_column(Integer, default=0)


class Audit(Base):
    __tablename__ = "gateway_audit"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), unique=True)
    tenant_id: Mapped[str] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
