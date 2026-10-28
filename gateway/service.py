import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError

from gateway.models import Application, Audit, Event
from gateway.schemas import CreditEvent

TRANSITIONS = {
    "pending": {"submitted"},
    "submitted": {"approved", "declined"},
    "approved": {"funded"},
    "declined": set(),
    "funded": set(),
}


class IdentityConflict(Exception):
    pass


def receive(factory, tenant: str, payload: CreditEvent, now: datetime):
    data = payload.model_dump(mode="json")
    data["occurred_at"] = payload.occurred_at.astimezone(UTC).isoformat()
    digest = hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    with factory() as session:
        row = Event(
            id=str(uuid4()),
            tenant_id=tenant,
            event_id=payload.event_id,
            application_id=payload.application_id,
            sequence=payload.sequence,
            event_type=payload.event_type,
            payload=data,
            payload_hash=digest,
            created_at=now,
            available_at=now,
        )
        session.add(row)
        try:
            session.commit()
            return row, True
        except IntegrityError:
            session.rollback()
            existing = session.scalar(
                select(Event).where(Event.tenant_id == tenant, Event.event_id == payload.event_id)
            )
            if existing is None:
                raise
            if existing.payload_hash != digest:
                raise IdentityConflict from None
            return existing, False


def process_one(factory, settings, now: datetime) -> str | None:
    """Claim and apply in one transaction. Crashes before commit roll everything back."""
    with factory.begin() as session:
        event = session.scalar(
            select(Event)
            .where(Event.status == "queued", Event.available_at <= now)
            .order_by(Event.available_at, Event.created_at, Event.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if event is None:
            return None
        insert = pg_insert if session.bind.dialect.name == "postgresql" else sqlite_insert
        session.execute(
            insert(Application)
            .values(
                tenant_id=event.tenant_id,
                application_id=event.application_id,
                status="pending",
                last_sequence=0,
            )
            .on_conflict_do_nothing(index_elements=["tenant_id", "application_id"])
        )
        application = session.scalar(
            select(Application)
            .where(
                Application.tenant_id == event.tenant_id,
                Application.application_id == event.application_id,
            )
            .with_for_update()
        )
        event.attempts += 1
        if event.sequence > application.last_sequence + 1:
            if event.attempts < settings.max_attempts:
                event.available_at = now + timedelta(seconds=settings.retry_delay)
                return "deferred"
            event.status, event.reason = "rejected", "sequence_gap"
        elif event.sequence <= application.last_sequence:
            event.status, event.reason = "rejected", "stale_sequence"
        elif event.event_type not in TRANSITIONS[application.status]:
            event.status, event.reason = "rejected", "invalid_transition"
        else:
            application.status = event.event_type
            application.last_sequence = event.sequence
            event.status = "processed"
        session.add(
            Audit(
                id=str(uuid4()),
                event_id=event.id,
                tenant_id=event.tenant_id,
                outcome=event.status,
                reason=event.reason,
                created_at=now,
            )
        )
        return event.status


def utc_now() -> datetime:
    return datetime.now(UTC)
