import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from gateway.api import create_app
from gateway.config import Partner, Settings
from gateway.models import Base
from gateway.security import sign

NOW = 1793200000
KEY_A = "synthetic-partner-alpha"
KEY_B = "synthetic-partner-beta"
SECRET_A = "synthetic-hmac-secret-alpha-only-tests"
SECRET_B = "synthetic-hmac-secret-beta-only-tests"


@pytest.fixture
def settings(tmp_path):
    return Settings(
        f"sqlite:///{tmp_path / 'gateway.db'}",
        {KEY_A: Partner("tenant-a", SECRET_A), KEY_B: Partner("tenant-b", SECRET_B)},
        retry_delay=1,
        max_attempts=3,
    )


@pytest.fixture
def app(settings):
    instance = create_app(settings, clock=lambda: NOW)
    Base.metadata.create_all(instance.state.engine)
    yield instance
    instance.state.engine.dispose()


@pytest.fixture
def client(app):
    with TestClient(app) as instance:
        yield instance


@pytest.fixture
def payload():
    return {
        "event_id": "synthetic-event-1",
        "application_id": "synthetic-application-1",
        "sequence": 1,
        "event_type": "submitted",
        "occurred_at": "2026-10-28T12:00:00Z",
    }


def signed(payload, key=KEY_A, secret=SECRET_A, timestamp=NOW):
    body = json.dumps(payload, separators=(",", ":")).encode()
    headers = {
        "X-Api-Key": key,
        "X-Webhook-Timestamp": str(timestamp),
        "X-Webhook-Signature": sign(secret, str(timestamp), body),
        "Content-Type": "application/json",
    }
    return {"content": body, "headers": headers}


def at(seconds=0):
    return datetime.fromtimestamp(NOW + seconds, UTC)
