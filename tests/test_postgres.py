import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url

from gateway.db import session_factory
from gateway.models import Application, Audit, Base, Event
from gateway.schemas import CreditEvent
from gateway.service import IdentityConflict, process_one, receive
from tests.conftest import at

pytestmark = pytest.mark.postgres


@pytest.fixture
def postgres(settings):
    configured = os.getenv("TEST_DATABASE_URL")
    if not configured:
        pytest.skip("TEST_DATABASE_URL required for PostgreSQL integration")
    url = make_url(configured)
    if url.drivername != "postgresql+psycopg" or not (url.database or "").endswith("_test"):
        pytest.fail("Use an isolated PostgreSQL psycopg database ending in _test")
    schema = "test_gateway_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    scoped = url.update_query_dict({"options": "-csearch_path=" + schema})
    engine, factory = session_factory(scoped.render_as_string(hide_password=False))
    Base.metadata.create_all(engine)
    yield factory, replace(settings, database_url=scoped.render_as_string(hide_password=False))
    engine.dispose()
    with admin.begin() as connection:
        connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    admin.dispose()


def model(payload, **updates):
    return CreditEvent.model_validate_json(json.dumps({**payload, **updates}))


def test_concurrent_delivery_one_receipt(postgres, payload):
    factory, _ = postgres
    data = model(payload)
    with ThreadPoolExecutor(max_workers=8) as pool:
        receipts = list(pool.map(lambda _: receive(factory, "tenant-a", data, at()), range(24)))
    assert sum(created for _, created in receipts) == 1
    assert len({row.id for row, _ in receipts}) == 1
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Event)) == 1


def test_concurrent_payload_conflict(postgres, payload):
    factory, _ = postgres

    def submit(kind):
        try:
            receive(factory, "tenant-a", model(payload, event_type=kind), at())
            return "accepted"
        except IdentityConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, ["submitted", "approved"]))
    assert sorted(results) == ["accepted", "conflict"]


def test_workers_skip_locked_and_complete_once(postgres, payload):
    factory, settings = postgres
    for number in range(16):
        receive(
            factory,
            "tenant-a",
            model(payload, event_id=f"event-{number}", application_id=f"application-{number}"),
            at(),
        )
    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(lambda _: process_one(factory, settings, at()), range(24)))
    assert outcomes.count("processed") == 16
    assert outcomes.count(None) == 8
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Audit)) == 16
        assert session.scalar(select(func.count()).select_from(Application)) == 16


def test_application_row_serializes_concurrent_sequences(postgres, payload):
    factory, settings = postgres
    receive(factory, "tenant-a", model(payload), at())
    process_one(factory, settings, at())
    for event_id in ["second-a", "second-b"]:
        receive(
            factory,
            "tenant-a",
            model(payload, event_id=event_id, sequence=2, event_type="approved"),
            at(),
        )
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: process_one(factory, settings, at()), range(2)))
    assert sorted(results) == ["processed", "rejected"]
    with factory() as session:
        assert session.get(Application, ("tenant-a", payload["application_id"])).last_sequence == 2


def test_database_checks_are_enforced(postgres, payload):
    from sqlalchemy.exc import IntegrityError

    factory, _ = postgres
    row, _ = receive(factory, "tenant-a", model(payload), at())
    with pytest.raises(IntegrityError), factory.begin() as session:
        session.execute(text("UPDATE gateway_events SET attempts=-1 WHERE id=:id"), {"id": row.id})
    with factory() as session:
        assert session.get(Event, row.id).attempts == 0
