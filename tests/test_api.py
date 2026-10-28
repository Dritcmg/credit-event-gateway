import json

import pytest
from fastapi.testclient import TestClient

from gateway.api import create_app
from gateway.security import sign
from tests.conftest import KEY_A, KEY_B, NOW, SECRET_A, SECRET_B, signed


def test_signed_acceptance(client, payload):
    response = client.post("/v1/events", **signed(payload))
    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert response.json()["attempts"] == 0
    assert "payload" not in response.json()
    assert "X-Request-Id" in response.headers


def test_duplicate_returns_same_receipt(client, payload):
    first = client.post("/v1/events", **signed(payload))
    duplicate = client.post("/v1/events", **signed(payload))
    assert duplicate.status_code == 200
    assert duplicate.json()["id"] == first.json()["id"]
    assert len(client.get("/v1/events", headers={"X-Api-Key": KEY_A}).json()) == 1


def test_identity_conflict(client, payload):
    client.post("/v1/events", **signed(payload))
    payload["event_type"] = "approved"
    assert client.post("/v1/events", **signed(payload)).status_code == 409


def test_equivalent_timezone_and_json_order_keep_same_identity(client, payload):
    first = client.post("/v1/events", **signed(payload))
    payload["occurred_at"] = "2026-10-28T09:00:00-03:00"
    reordered = dict(reversed(list(payload.items())))
    replay = client.post("/v1/events", **signed(reordered))
    assert replay.status_code == 200
    assert replay.json()["id"] == first.json()["id"]


@pytest.mark.parametrize("headers", [{}, {"X-Api-Key": "unknown"}])
def test_missing_or_unknown_credential(client, payload, headers):
    assert client.post("/v1/events", json=payload, headers=headers).status_code == 401


def test_partner_cannot_read_another_tenant(client, payload):
    receipt = client.post("/v1/events", **signed(payload)).json()["id"]
    assert client.get(f"/v1/events/{receipt}", headers={"X-Api-Key": KEY_B}).status_code == 404
    assert client.get("/v1/events", headers={"X-Api-Key": KEY_B}).json() == []


def test_same_event_id_is_independent_across_tenants(client, payload):
    first = client.post("/v1/events", **signed(payload))
    second = client.post("/v1/events", **signed(payload, KEY_B, SECRET_B))
    assert first.status_code == second.status_code == 202
    assert first.json()["id"] != second.json()["id"]


@pytest.mark.parametrize("timestamp", [NOW - 301, NOW + 301])
def test_stale_and_future_signatures(client, payload, timestamp):
    assert client.post("/v1/events", **signed(payload, timestamp=timestamp)).status_code == 401


@pytest.mark.parametrize("value", ["", "yesterday", "-1", "1" * 40])
def test_invalid_timestamp(client, payload, value):
    args = signed(payload)
    args["headers"]["X-Webhook-Timestamp"] = value
    assert client.post("/v1/events", **args).status_code == 401


def test_body_tampering_invalidates_signature(client, payload):
    args = signed(payload)
    args["content"] += b" "
    assert client.post("/v1/events", **args).status_code == 401


def test_secret_of_other_partner_is_not_valid(client, payload):
    assert client.post("/v1/events", **signed(payload, secret=SECRET_B)).status_code == 401


@pytest.mark.parametrize(
    "changes",
    [
        {"tenant_id": "tenant-b"},
        {"sequence": "1"},
        {"sequence": 0},
        {"sequence": True},
        {"event_type": "paid"},
        {"event_id": "../private"},
        {"occurred_at": "2026-10-28T12:00:00"},
        {"event_id": "a" * 65},
    ],
)
def test_strict_payload_validation(client, payload, changes):
    payload.update(changes)
    response = client.post("/v1/events", **signed(payload))
    assert response.status_code == 422
    assert all("input" not in error for error in response.json()["detail"])


def test_invalid_json_is_rejected_without_echo(client):
    body = b'{"untrusted":broken}'
    response = client.post(
        "/v1/events",
        content=body,
        headers={
            "X-Api-Key": KEY_A,
            "X-Webhook-Timestamp": str(NOW),
            "X-Webhook-Signature": sign(SECRET_A, str(NOW), body),
        },
    )
    assert response.status_code == 422
    assert "broken" not in response.text


def test_oversized_body(client):
    args = signed({"oversized": "x" * 66000})
    assert client.post("/v1/events", **args).status_code == 413


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1", "offset=10001"])
def test_pagination_bounds(client, query):
    assert client.get("/v1/events?" + query, headers={"X-Api-Key": KEY_A}).status_code == 422


def test_pagination_and_unknown_receipt(client, payload):
    for number in range(3):
        payload["event_id"] = f"event-{number}"
        client.post("/v1/events", **signed(payload))
    response = client.get("/v1/events?offset=1&limit=1", headers={"X-Api-Key": KEY_A})
    assert len(response.json()) == 1
    assert client.get("/v1/events/missing", headers={"X-Api-Key": KEY_A}).status_code == 404


def test_receipt_survives_app_restart(client, settings, payload):
    receipt = client.post("/v1/events", **signed(payload)).json()
    restarted = create_app(settings, clock=lambda: NOW)
    try:
        with TestClient(restarted) as fresh:
            response = fresh.get(f"/v1/events/{receipt['id']}", headers={"X-Api-Key": KEY_A})
            assert response.json()["id"] == receipt["id"]
            assert fresh.post("/v1/events", **signed(payload)).status_code == 200
    finally:
        restarted.state.engine.dispose()


def test_health_and_openapi(client):
    assert client.get("/health/live").json() == {"status": "alive"}
    assert client.get("/health/ready").json() == {"status": "ready"}
    schema = client.get("/openapi.json").json()
    assert "/v1/events" in schema["paths"]
    assert "APIKeyHeader" in json.dumps(schema)
