import asyncio
import threading

import httpx
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from gateway import api, worker
from gateway.models import Audit, Event
from gateway.schemas import CreditEvent
from gateway.service import process_one, receive
from tests.conftest import at, signed


def test_blocked_database_write_does_not_block_health_request(app, payload, monkeypatch):
    started, release = threading.Event(), threading.Event()
    original = api.receive

    def slow_receive(*args):
        started.set()
        if not release.wait(3):
            raise RuntimeError("controlled slow transaction was not released")
        return original(*args)

    monkeypatch.setattr(api, "receive", slow_receive)

    async def requests():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://synthetic.test"
        ) as client:
            pending = asyncio.create_task(client.post("/v1/events", **signed(payload)))
            try:
                assert await asyncio.to_thread(started.wait, 1)
                health = await asyncio.wait_for(client.get("/health/live"), 1)
                assert health.status_code == 200
                assert not pending.done(), "Health must respond while database write is blocked"
            finally:
                release.set()
            assert (await pending).status_code == 202

    asyncio.run(requests())


def test_worker_retries_transient_database_failure_and_applies_event_once(
    app, settings, payload, monkeypatch, capsys
):
    import json

    row, _ = receive(
        app.state.factory, "tenant-a", CreditEvent.model_validate_json(json.dumps(payload)), at()
    )
    attempts, waits = [], []

    def transient(factory, configured, now):
        attempts.append(1)
        if len(attempts) < 3:
            raise OperationalError("private-db-password", {}, Exception("private-error-detail"))
        return process_one(factory, configured, now)

    monkeypatch.setattr(worker, "process_one", transient)
    result = worker.run_worker(app.state.factory, settings, once=True, wait=waits.append, now=at)
    assert result == 0
    assert len(attempts) == 3
    assert waits == [1, 2]
    with app.state.factory() as session:
        assert session.get(Event, row.id).status == "processed"
        assert len(session.scalars(select(Audit)).all()) == 1
    logs = capsys.readouterr().out
    assert "worker_database_retry" in logs
    assert "private-db-password" not in logs
    assert "private-error-detail" not in logs


def test_worker_failure_budget_exhaustion_exits_without_busy_loop(settings, monkeypatch, capsys):
    attempts, waits = [], []

    def unavailable(*_args):
        attempts.append(1)
        raise OperationalError("private-db-password", {}, Exception("private-error-detail"))

    monkeypatch.setattr(worker, "process_one", unavailable)
    assert worker.run_worker(None, settings, max_failures=3, wait=waits.append) == 1
    assert len(attempts) == 3
    assert waits == [1, 2]
    logs = capsys.readouterr().out
    assert "worker_failure_budget_exhausted" in logs
    assert "private-db-password" not in logs


def test_worker_stop_interrupts_backoff(settings, monkeypatch):
    stop = threading.Event()
    attempts = []

    def unavailable(*_args):
        attempts.append(1)
        raise OperationalError("private", {}, Exception())

    def interruptible_wait(_seconds):
        stop.set()
        return True

    monkeypatch.setattr(worker, "process_one", unavailable)
    assert worker.run_worker(None, settings, stop=stop, wait=interruptible_wait) == 0
    assert len(attempts) == 1
