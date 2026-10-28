from unittest.mock import patch

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session, sessionmaker

from gateway.models import Application, Audit, Event
from gateway.schemas import CreditEvent
from gateway.service import process_one, receive
from tests.conftest import KEY_A, KEY_B, SECRET_B, at, signed


def ingest(factory, payload, sequence, kind, tenant="tenant-a"):
    data = {
        **payload,
        "event_id": f"event-{sequence}-{kind}",
        "sequence": sequence,
        "event_type": kind,
    }
    return receive(
        factory, tenant, CreditEvent.model_validate_json(__import__("json").dumps(data)), at()
    )[0]


def test_in_order_state_and_audit(app, settings, payload, client):
    factory = app.state.factory
    for seq, kind in [(1, "submitted"), (2, "approved"), (3, "funded")]:
        ingest(factory, payload, seq, kind)
        assert process_one(factory, settings, at()) == "processed"
    with factory() as session:
        state = session.get(Application, ("tenant-a", payload["application_id"]))
        assert (state.status, state.last_sequence) == ("funded", 3)
        assert session.scalar(select(func.count()).select_from(Audit)) == 3
    response = client.get(
        "/v1/applications/" + payload["application_id"], headers={"X-Api-Key": KEY_A}
    )
    assert response.json()["status"] == "funded"
    assert (
        client.get(
            "/v1/applications/" + payload["application_id"], headers={"X-Api-Key": KEY_B}
        ).status_code
        == 404
    )


def test_out_of_order_defers_then_recovers(app, settings, payload):
    factory = app.state.factory
    ingest(factory, payload, 2, "approved")
    assert process_one(factory, settings, at()) == "deferred"
    ingest(factory, payload, 1, "submitted")
    assert process_one(factory, settings, at()) == "processed"
    assert process_one(factory, settings, at(2)) == "processed"
    assert process_one(factory, settings, at(2)) is None
    with factory() as session:
        assert (
            session.get(Application, ("tenant-a", payload["application_id"])).status == "approved"
        )


def test_gap_is_bounded_and_has_audit(app, settings, payload):
    factory = app.state.factory
    row = ingest(factory, payload, 3, "funded")
    assert process_one(factory, settings, at()) == "deferred"
    assert process_one(factory, settings, at()) is None
    assert process_one(factory, settings, at(2)) == "deferred"
    assert process_one(factory, settings, at(4)) == "rejected"
    with factory() as session:
        stored = session.get(Event, row.id)
        assert (stored.reason, stored.attempts) == ("sequence_gap", 3)
        assert session.scalar(select(Audit).where(Audit.event_id == row.id)).outcome == "rejected"


def test_invalid_transition_does_not_advance_state(app, settings, payload):
    factory = app.state.factory
    row = ingest(factory, payload, 1, "funded")
    assert process_one(factory, settings, at()) == "rejected"
    with factory() as session:
        assert session.get(Event, row.id).reason == "invalid_transition"
        assert session.get(Application, ("tenant-a", payload["application_id"])).last_sequence == 0


def test_two_distinct_events_same_sequence_are_not_applied_twice(app, settings, payload):
    factory = app.state.factory
    ingest(factory, payload, 1, "submitted")
    assert process_one(factory, settings, at()) == "processed"
    row = ingest(factory, payload, 1, "approved")
    assert process_one(factory, settings, at()) == "rejected"
    with factory() as session:
        assert session.get(Event, row.id).reason == "stale_sequence"


def test_decline_is_terminal(app, settings, payload):
    factory = app.state.factory
    for seq, kind in [(1, "submitted"), (2, "declined")]:
        ingest(factory, payload, seq, kind)
        assert process_one(factory, settings, at()) == "processed"
    ingest(factory, payload, 3, "funded")
    assert process_one(factory, settings, at()) == "rejected"


def test_commit_failure_rolls_back_state_receipt_and_audit(app, settings, payload):
    factory = app.state.factory
    row = ingest(factory, payload, 1, "submitted")

    class FailingSession(Session):
        pass

    @event.listens_for(FailingSession, "before_commit")
    def crash(_session):
        raise RuntimeError("controlled failure before commit")

    failed_factory = sessionmaker(app.state.engine, class_=FailingSession)
    with pytest.raises(RuntimeError, match="controlled failure"):
        process_one(failed_factory, settings, at())
    with factory() as session:
        assert session.get(Event, row.id).status == "queued"
        assert session.get(Event, row.id).attempts == 0
        assert session.get(Application, ("tenant-a", payload["application_id"])) is None
        assert session.scalar(select(func.count()).select_from(Audit)) == 0
    assert process_one(factory, settings, at()) == "processed"


def test_worker_restart_reuses_persisted_state(app, settings, payload):
    factory = app.state.factory
    ingest(factory, payload, 1, "submitted")
    process_one(factory, settings, at())
    ingest(factory, payload, 2, "approved")
    fresh = sessionmaker(app.state.engine, expire_on_commit=False)
    assert process_one(fresh, settings, at()) == "processed"


def test_requests_log_never_contains_credentials_or_body(client, payload, caplog):
    with caplog.at_level("INFO", logger="credit_gateway"):
        client.post("/v1/events", **signed(payload))
    messages = " ".join(str(record.__dict__) for record in caplog.records)
    assert "synthetic-hmac-secret" not in messages
    assert KEY_A not in messages
    assert "application-1" not in messages


def test_duplicate_after_processing_keeps_outcome(client, app, settings, payload):
    client.post("/v1/events", **signed(payload))
    process_one(app.state.factory, settings, at())
    response = client.post("/v1/events", **signed(payload))
    assert response.status_code == 200
    assert response.json()["status"] == "processed"


def test_readiness_does_not_expose_database_error(client, app):
    from sqlalchemy.exc import OperationalError

    with patch.object(
        app.state.engine, "connect", side_effect=OperationalError("private", {}, Exception())
    ):
        response = client.get("/health/ready")
    assert response.status_code == 503
    assert "private" not in response.text


def test_tenants_have_independent_application_state(client, app, settings, payload):
    client.post("/v1/events", **signed(payload))
    client.post("/v1/events", **signed(payload, KEY_B, SECRET_B))
    assert process_one(app.state.factory, settings, at()) == "processed"
    assert process_one(app.state.factory, settings, at()) == "processed"
    with app.state.factory() as session:
        assert session.scalar(select(func.count()).select_from(Application)) == 2
