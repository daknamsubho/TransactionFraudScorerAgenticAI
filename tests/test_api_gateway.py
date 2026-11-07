"""Unit and integration tests for the FastAPI Gateway (REST & WebSocket endpoints)."""

from pathlib import Path
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


def test_health_endpoint(tmp_path: Path) -> None:
    """Verify GET /health returns status ok and configured agent_flags."""
    client = TestClient(create_app(db_path=tmp_path / "test.db"))
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "ollama_connected" in body
    assert "agent_flags" in body
    assert body["agent_flags"]["enable_orchestrator_agent"] is True
    assert body["agent_flags"]["enable_decision_agent"] is True


def test_ingest_card_transaction_score(tmp_path: Path) -> None:
    """Verify POST /api/v1/transactions/score scores a normal CARD transaction via Decision Agent as APPROVE."""
    client = TestClient(create_app(db_path=tmp_path / "test.db"))
    response = client.post("/api/v1/transactions/score", json=_sample_card_payload())
    assert response.status_code == 200
    data = response.json()
    assert data["transaction_id"].startswith("tx_")
    assert data["score"] < 30.0
    assert data["status"] == "APPROVE"


def test_ingest_ach_transaction_score(tmp_path: Path) -> None:
    """Verify POST /api/v1/transactions/score scores a suspicious ACH transaction via Decision Agent as DECLINE."""
    client = TestClient(create_app(db_path=tmp_path / "test.db"))
    response = client.post("/api/v1/transactions/score", json=_sample_ach_payload())
    assert response.status_code == 200
    data = response.json()
    assert data["transaction_id"].startswith("tx_")
    assert data["score"] >= 70.0
    assert data["status"] == "DECLINE"


def test_ingest_validation_error_missing_rail_details(tmp_path: Path) -> None:
    """Verify 422 validation error when transaction_type is CARD but card_details is omitted."""
    client = TestClient(create_app(db_path=tmp_path / "test.db"))
    bad_payload = _sample_card_payload()
    del bad_payload["transaction_details"]["card_details"]

    response = client.post("/api/v1/transactions/score", json=bad_payload)
    assert response.status_code == 422


def test_websocket_receives_scored_transaction_event(tmp_path: Path) -> None:
    """Verify connected WebSocket receives WebSocketTransactionEvent with Decision Agent score and status."""
    client = TestClient(create_app(db_path=tmp_path / "test.db"))

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
        assert event["score_details"]["request_payload"]["username"] == "jdoe_99"
        assert event["score_details"]["request_payload"]["transaction_details"]["amount"] == 2200.0
        assert isinstance(event["score_details"]["risk_factors"], list)
        assert isinstance(event["score_details"]["reasoning_summary"], str)
        assert len(event["score_details"]["tools_invoked"]) >= 4


def test_decision_accept_and_reject(tmp_path: Path) -> None:
    """Verify POST /api/v1/transactions/decision accepts, rejects, and handles unknown IDs."""
    client = TestClient(create_app(db_path=tmp_path / "test.db"))

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


def test_rdbms_crud_and_paginated_endpoints(tmp_path: Path) -> None:
    """Verify GET (paginated & single), POST, PUT, and DELETE across all 3 RDBMS tables."""
    db_file = tmp_path / "gateway_rdbms.db"
    client = TestClient(create_app(db_path=db_file))

    # 1. User Profiles CRUD & Pagination
    create_up = client.post(
        "/api/v1/db/user-profiles",
        json={
            "username": "user_01",
            "address": "101 First St",
            "city": "Austin",
            "state": "TX",
            "country": "US",
            "postal_code": "78701",
        },
    )
    assert create_up.status_code == 200
    assert create_up.json()["username"] == "user_01"

    list_up = client.get("/api/v1/db/user-profiles?page=1&page_size=5")
    assert list_up.status_code == 200
    list_up_data = list_up.json()
    assert list_up_data["total"] == 1
    assert list_up_data["page"] == 1
    assert list_up_data["items"][0]["city"] == "Austin"

    update_up = client.put(
        "/api/v1/db/user-profiles/user_01",
        json={"address": "202 Second St", "city": "Dallas", "state": "TX", "country": "US", "postal_code": "75201"},
    )
    assert update_up.status_code == 200
    assert update_up.json()["city"] == "Dallas"

    get_up = client.get("/api/v1/db/user-profiles/user_01")
    assert get_up.status_code == 200
    assert get_up.json()["address"] == "202 Second St"

    # 2. Transactions CRUD & Pagination
    create_tx = client.post(
        "/api/v1/db/transactions",
        json={
            "transaction_id": "tx_rdbms_100",
            "username": "user_01",
            "transaction_type": "CARD",
            "amount": 320.50,
            "latitude": 32.7767,
            "longitude": -96.7970,
            "city": "Dallas",
            "state": "TX",
            "country": "US",
            "merchant_name": "Lone Star Electronics",
            "status": "REVIEW",
        },
    )
    assert create_tx.status_code == 200
    assert create_tx.json()["transaction_id"] == "tx_rdbms_100"

    list_tx = client.get("/api/v1/db/transactions?page=1&page_size=5&status=REVIEW")
    assert list_tx.status_code == 200
    assert list_tx.json()["total"] == 1

    update_tx = client.put(
        "/api/v1/db/transactions/tx_rdbms_100",
        json={"amount": 350.00, "status": "APPROVE"},
    )
    assert update_tx.status_code == 200
    assert update_tx.json()["amount"] == 350.00
    assert update_tx.json()["status"] == "APPROVE"

    # 3. Transaction Scores CRUD & Pagination
    create_score = client.post(
        "/api/v1/db/transaction-scores",
        json={
            "transaction_id": "tx_rdbms_100",
            "score": 18.5,
            "approval_status": "APPROVE",
            "reasoning_summary": "Low risk purchase in home state.",
            "tools_invoked": ["check_velocity"],
        },
    )
    assert create_score.status_code == 200
    assert create_score.json()["score"] == 18.5

    list_scores = client.get("/api/v1/db/transaction-scores?page=1&page_size=5")
    assert list_scores.status_code == 200
    assert list_scores.json()["total"] == 1

    update_score = client.put(
        "/api/v1/db/transaction-scores/tx_rdbms_100",
        json={
            "score": 65.0,
            "approval_status": "ACCEPTED",
            "decision_accepted": True,
            "decision_reason": "Approved by analyst.",
            "reasoning_summary": "Updated after manual review.",
        },
    )
    assert update_score.status_code == 200
    assert update_score.json()["score"] == 65.0
    assert update_score.json()["decision_accepted"] is True

    # 4. DELETE score, transaction, and user_profile
    del_score = client.delete("/api/v1/db/transaction-scores/tx_rdbms_100")
    assert del_score.status_code == 200
    assert del_score.json()["deleted"] is True

    del_tx = client.delete("/api/v1/db/transactions/tx_rdbms_100")
    assert del_tx.status_code == 200
    assert del_tx.json()["deleted"] is True

    del_user = client.delete("/api/v1/db/user-profiles/user_01")
    assert del_user.status_code == 200
    assert del_user.json()["deleted"] is True


def test_end_to_end_gateway_fraud_scorer_db_and_feedback(tmp_path: Path) -> None:
    """Verify API Gateway -> OrchestratorAgent -> SQLite DB -> WebClient Feedback loop (PRD-010)."""
    db_file = tmp_path / "e2e_fraud_scorer.db"
    client = TestClient(create_app(db_path=db_file))

    # 1. Create a user profile in SQLite
    client.post(
        "/api/v1/db/user-profiles",
        json={
            "username": "live_user_01",
            "created_date": "2025-01-01T00:00:00Z",
            "address": "100 Main St",
            "city": "San Francisco",
            "state": "CA",
            "country": "US",
            "postal_code": "94105",
        },
    )

    # 2. First normal transaction in San Francisco ($45.00 grocery) -> APPROVE
    tx1_payload = _sample_card_payload(username="live_user_01", amount=45.0)
    tx1_payload["datetime"] = "2026-10-31T18:00:00Z"
    resp1 = client.post("/api/v1/transactions/score", json=tx1_payload)
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["status"] == "APPROVE"
    assert data1["score"] == 0.0
    assert data1["assessment_id"].startswith("assess_")
    assert isinstance(data1["reasoning_summary"], str)
    assert len(data1["tools_invoked"]) >= 4

    # 3. Second transaction 15 minutes later in Tokyo ($3,200.00 casino MCC 7995) -> DECLINE
    tx2_payload = _sample_card_payload(username="live_user_01", amount=3200.0)
    tx2_payload["datetime"] = "2026-10-31T18:15:00Z"
    tx2_payload["location"] = {
        "latitude": 35.6762,
        "longitude": 139.6503,
        "city": "Tokyo",
        "country": "JP",
    }
    tx2_payload["transaction_details"]["merchant"] = {
        "merchant_id": "merch_tokyo_casino",
        "name": "Tokyo High Roller Casino",
        "mcc": "7995",
        "country": "JP",
    }
    tx2_payload["transaction_details"]["card_details"]["is_card_present"] = False

    resp2 = client.post("/api/v1/transactions/score", json=tx2_payload)
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["status"] == "DECLINE"
    assert data2["score"] >= 70.0
    categories = [rf["category"] for rf in data2["risk_factors"]]
    assert "GEO_ANOMALY" in categories
    assert "MERCHANT_RISK" in categories
    assert "AMOUNT_ANOMALY" in categories

    # 4. Submit WebClient Analyst Feedback (Reject with reason)
    feedback_resp = client.post(
        "/api/v1/transactions/decision",
        json={
            "transaction_id": data2["transaction_id"],
            "accept": False,
            "reason": "Confirmed impossible travel and high-risk MCC via WebClient.",
        },
    )
    assert feedback_resp.status_code == 200
    assert feedback_resp.json()["decision_applied"] == "REJECTED"

    # 5. Verify SQLite transaction_scores record has the feedback persisted
    score_record = client.get(f"/api/v1/db/transaction-scores/{data2['transaction_id']}").json()
    assert score_record["approval_status"] == "REJECTED"
    assert score_record["decision_accepted"] is False
    assert score_record["decision_reason"] == "Confirmed impossible travel and high-risk MCC via WebClient."


def test_vector_db_gateway_endpoints(tmp_path: Path) -> None:
    """Verify PRD-016 ChromaDB API Gateway endpoints: stats, query (top_k, year, category), and document upload."""
    db_file = tmp_path / "vector_gateway.db"
    chroma_dir = tmp_path / "chroma_store"
    client = TestClient(create_app(db_path=db_file, chroma_dir=chroma_dir))

    # 1. GET /api/v1/vector/stats should auto-seed 26 policy chunks (13 for 2025, 13 for 2026)
    stats_resp = client.get("/api/v1/vector/stats")
    assert stats_resp.status_code == 200
    stats_data = stats_resp.json()
    assert stats_data["collection_name"] == "fraud_policies"
    assert stats_data["total_documents"] == 26
    assert stats_data["chunks_per_year"]["2025"] == 13
    assert stats_data["chunks_per_year"]["2026"] == 13

    # 2. POST /api/v1/vector/query with top_k and policy_year filter
    q2025_resp = client.post(
        "/api/v1/vector/query",
        json={
            "query": "cryptocurrency exchange MCC 6051 transaction over $3000",
            "top_k": 2,
            "policy_year": "2025",
        },
    )
    assert q2025_resp.status_code == 200
    q2025_data = q2025_resp.json()
    assert q2025_data["top_k"] == 2
    assert q2025_data["total_results"] == 2
    assert all(item["policy_year"] == "2025" for item in q2025_data["results"])
    assert q2025_data["results"][0]["clause_id"].startswith("POL-2025-")

    q2026_resp = client.post(
        "/api/v1/vector/query",
        json={
            "query": "cryptocurrency exchange MCC 6051 transaction over $3000",
            "top_k": 2,
            "policy_year": "2026",
            "category": "MCC_RULES",
        },
    )
    assert q2026_resp.status_code == 200
    q2026_data = q2026_resp.json()
    assert q2026_data["total_results"] >= 1
    assert all(item["policy_year"] == "2026" for item in q2026_data["results"])
    assert all(item["category"] == "MCC_RULES" for item in q2026_data["results"])

    # 3. POST /api/v1/vector/documents to upload a new custom policy rule
    upload_resp = client.post(
        "/api/v1/vector/documents",
        json={
            "content": "Transactions originating from satellite VPN relays over $1,500 require mandatory step-up biometric verification.",
            "title": "Satellite VPN Relay Step-Up Rule",
            "clause_id": "POL-2026-VPN-01",
            "policy_year": "2026",
            "category": "DEVICE_SECURITY",
            "filename": "custom-vpn-policy-2026.md",
        },
    )
    assert upload_resp.status_code == 201
    upload_data = upload_resp.json()
    assert upload_data["status"] == "SUCCESS"
    assert upload_data["chunks_ingested"] == 1
    assert upload_data["ingested_ids"] == ["pol_2026_pol_2026_vpn_01"]
    assert upload_data["collection_count"] == 27

    # 4. GET /api/v1/vector/documents filtered by policy_year
    list_docs_resp = client.get("/api/v1/vector/documents?policy_year=2026&limit=20")
    assert list_docs_resp.status_code == 200
    list_docs_data = list_docs_resp.json()
    returned_clauses = {item["clause_id"] for item in list_docs_data["items"]}
    assert "POL-2026-VPN-01" in returned_clauses

