"""Unit and integration tests for the FastAPI Gateway (REST & WebSocket endpoints)."""

from typing import Any

from fastapi.testclient import TestClient

from api_gateway.app import create_app


def _sample_card_payload(username: str = "acc_normal_01", amount: float = 55.0) -> dict[str, Any]:
    """Return a valid Card transaction ingestion payload."""
    return {
        "username": username,
        "datetime": "2026-10-31T18:09:11Z",
        "ip": "198.51.100.42",
        "device_id": "dev_macbook_pro_91a",
        "location": {
            "latitude": 37.7749,
            "longitude": -122.4194,
            "city": "San Francisco",
            "state": "CA",
            "country": "US",
            "postal_code": "94103",
        },
        "transaction_details": {
            "transaction_type": "CARD",
            "amount": amount,
            "currency": "USD",
            "merchant": {
                "merchant_id": "m_supermarket_1",
                "name": "Whole Foods Market",
                "mcc": "5411",
                "country": "US",
            },
            "card_details": {
                "card_type": "CREDIT",
                "card_network": "VISA",
                "card_last_four": "4242",
                "is_card_present": True,
                "expiration_month": 8,
                "expiration_year": 2028,
                "cvv_verified": True,
                "avs_result": "Y",
            },
        },
    }


def _sample_ach_payload(username: str = "acc_suspicious_01", amount: float = 4800.0) -> dict[str, Any]:
    """Return a valid ACH transaction ingestion payload."""
    return {
        "username": username,
        "datetime": "2026-10-31T18:15:00Z",
        "ip": "198.51.100.42",
        "location": {
            "latitude": 35.6762,
            "longitude": 139.6503,
            "city": "Tokyo",
            "country": "JP",
        },
        "transaction_details": {
            "transaction_type": "ACH",
            "amount": amount,
            "currency": "USD",
            "merchant": {
                "merchant_id": "merch_crypto_99",
                "name": "Global Crypto Transfer",
                "mcc": "6051",
                "country": "JP",
            },
            "ach_details": {
                "routing_number": "021000021",
                "account_last_four": "9876",
                "account_type": "CHECKING",
                "sec_code": "WEB",
                "direction": "DEBIT",
                "bank_name": "Chase Bank",
            },
        },
    }


def test_health_endpoint() -> None:
    """Verify GET /health returns status ok."""
    client = TestClient(create_app())
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "ollama_connected" in body


def test_ingest_card_transaction_score() -> None:
    """Verify POST /api/v1/transactions/score scores a CARD transaction."""
    client = TestClient(create_app())
    response = client.post("/api/v1/transactions/score", json=_sample_card_payload())
    assert response.status_code == 200
    data = response.json()
    assert data["transaction_id"].startswith("tx_")
    assert 0.0 <= data["score"] <= 100.0
    assert data["status"] in ("APPROVE", "REVIEW", "DECLINE")


def test_ingest_ach_transaction_score() -> None:
    """Verify POST /api/v1/transactions/score scores an ACH transaction."""
    client = TestClient(create_app())
    response = client.post("/api/v1/transactions/score", json=_sample_ach_payload())
    assert response.status_code == 200
    data = response.json()
    assert data["transaction_id"].startswith("tx_")
    assert data["score"] >= 70.0
    assert data["status"] == "DECLINE"


def test_ingest_validation_error_missing_rail_details() -> None:
    """Verify 422 validation error when transaction_type is CARD but card_details is omitted."""
    client = TestClient(create_app())
    bad_payload = _sample_card_payload()
    del bad_payload["transaction_details"]["card_details"]

    response = client.post("/api/v1/transactions/score", json=bad_payload)
    assert response.status_code == 422


def test_websocket_receives_scored_transaction_event() -> None:
    """Verify connected WebSocket receives WebSocketTransactionEvent with username and score_details."""
    client = TestClient(create_app())

    with client.websocket_connect("/ws/transactions/events") as websocket:
        score_resp = client.post(
            "/api/v1/transactions/score",
            json=_sample_card_payload(username="jdoe_99", amount=2200.0),
        )
        assert score_resp.status_code == 200
        score_json = score_resp.json()

        event = websocket.receive_json()
        assert event["event_type"] == "TRANSACTION_SCORED"
        assert event["transaction_id"] == score_json["transaction_id"]
        assert event["username"] == "jdoe_99"
        assert event["amount"] == 2200.0
        assert event["score"] == score_json["score"]
        assert "score_details" in event
        assert event["score_details"]["status"] == score_json["status"]
        assert isinstance(event["score_details"]["risk_factors"], list)
        assert isinstance(event["score_details"]["reasoning_summary"], str)


def test_decision_accept_and_reject() -> None:
    """Verify POST /api/v1/transactions/decision accepts, rejects, and handles unknown IDs."""
    client = TestClient(create_app())

    # 1. Score a transaction first
    score_resp = client.post("/api/v1/transactions/score", json=_sample_card_payload())
    tx_id = score_resp.json()["transaction_id"]

    # 2. Accept the transaction
    accept_resp = client.post(
        "/api/v1/transactions/decision",
        json={
            "transaction_id": tx_id,
            "accept": True,
            "reason": "Verified customer via step-up 2FA.",
        },
    )
    assert accept_resp.status_code == 200
    accept_data = accept_resp.json()
    assert accept_data["status"] == "SUCCESS"
    assert accept_data["success"] is True
    assert accept_data["transaction_id"] == tx_id
    assert accept_data["decision_applied"] == "ACCEPTED"

    # 3. Reject the transaction
    reject_resp = client.post(
        "/api/v1/transactions/decision",
        json={
            "transaction_id": tx_id,
            "accept": False,
            "reason": "Chargeback alert received from issuer.",
        },
    )
    assert reject_resp.status_code == 200
    reject_data = reject_resp.json()
    assert reject_data["status"] == "SUCCESS"
    assert reject_data["success"] is True
    assert reject_data["decision_applied"] == "REJECTED"

    # 4. Unknown transaction ID returns 404 FAILURE
    not_found_resp = client.post(
        "/api/v1/transactions/decision",
        json={
            "transaction_id": "tx_nonexistent_999",
            "accept": False,
            "reason": "Unknown transaction test.",
        },
    )
    assert not_found_resp.status_code == 404
    nf_data = not_found_resp.json()
    assert nf_data["status"] == "FAILURE"
    assert nf_data["success"] is False
    assert nf_data["decision_applied"] is None
