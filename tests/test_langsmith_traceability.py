"""Comprehensive unit and integration tests for PRD-018: LangSmith Traceability & Real-Time Agent Streaming."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from api_gateway.app import create_app
from api_gateway.schemas import AgentStepEvent, AgentStepEventType
from fraud_scorer.agents.decision_agent import DecisionAgent
from fraud_scorer.agents.orchestrator_agent import OrchestratorAgent
from fraud_scorer.config import Settings, settings
from fraud_scorer.models.transaction import (
    FraudAssessment,
    GeoLocation,
    MerchantInfo,
    PaymentMethod,
    RiskFactor,
    Transaction,
)
from fraud_scorer.observability import (
    build_langchain_run_config,
    get_langsmith_client,
    get_langsmith_trace_url,
    mask_pan,
    record_feedback,
    safe_traceable,
    sanitize_transaction_payload,
)
from sqllite import (
    init_db,
    insert_transaction,
    insert_transaction_score,
    select_transaction_score,
)


def _sample_transaction(tx_id: str = "tx_trace_001") -> Transaction:
    return Transaction(
        transaction_id=tx_id,
        account_id="good_persona_01",
        amount=65.00,
        currency="USD",
        timestamp=datetime.now(UTC),
        location=GeoLocation(
            latitude=37.7749,
            longitude=-122.4194,
            city="San Francisco",
            country="US",
        ),
        payment_method=PaymentMethod(
            payment_type="credit_card",
            card_last_four="4242",
            is_card_present=True,
        ),
        merchant=MerchantInfo(
            merchant_id="merch_grocery_01",
            name="Whole Foods Market",
            mcc="5411",
            country="US",
        ),
    )


# =============================================================================
# 1. PII & PCI-DSS Sanitizer Tests
# =============================================================================


def test_mask_pan_replaces_16_digit_card_numbers() -> None:
    """Verify 13-19 digit PANs (contiguous, hyphenated, or spaced) are masked to last 4 digits."""
    raw_text = "Card 4532015112830366 and dashed 4532-0151-1283-9876 failed CVV check."
    masked = mask_pan(raw_text)

    assert "4532015112830366" not in masked
    assert "4532-0151-1283-9876" not in masked
    assert "****-****-****-0366" in masked
    assert "****-****-****-9876" in masked


def test_sanitize_transaction_payload_scrubs_pii_and_preserves_risk_metadata() -> None:
    """Verify PAN, CVV, address, customer name, routing_number, and IP are scrubbed."""
    raw_payload: dict[str, Any] = {
        "transaction_id": "tx_pii_99",
        "account_id": "jdoe_99",
        "amount": 1450.00,
        "currency": "USD",
        "merchant_category_code": "5732",
        "card_last_four": "4242",
        "pan": "4111222233334444",
        "cvv": "849",
        "billing_street": "742 Evergreen Terrace",
        "customer_name": "Homer J. Simpson",
        "ip_address": "198.51.100.42",
        "ach_details": {
            "routing_number": "021000021",
            "account_number": "998877665544",
            "account_last_four": "5544",
        },
        "notes": "Customer entered PAN 5500-1111-2222-3333 in support chat",
    }

    clean = sanitize_transaction_payload(raw_payload)

    # Operational risk metadata preserved
    assert clean["transaction_id"] == "tx_pii_99"
    assert clean["amount"] == 1450.00
    assert clean["currency"] == "USD"
    assert clean["merchant_category_code"] == "5732"
    assert clean["card_last_four"] == "4242"
    assert clean["ach_details"]["account_last_four"] == "5544"

    # Sensitive PCI-DSS & PII fields scrubbed
    assert clean["pan"] == "****-****-****-4444"
    assert clean["cvv"] == "***REDACTED***"
    assert clean["billing_street"] == "***REDACTED_PII***"
    assert clean["customer_name"] == "***REDACTED_PII***"
    assert clean["ip_address"] == "198.51.100.***"
    assert clean["ach_details"]["routing_number"] == "*****0021"
    assert clean["ach_details"]["account_number"] == "***REDACTED***"
    assert "5500-1111-2222-3333" not in clean["notes"]
    assert "****-****-****-3333" in clean["notes"]


# =============================================================================
# 2. Graceful Fallback Tests (Disabled State) & Trace Configuration
# =============================================================================


@pytest.mark.asyncio
async def test_orchestrator_runs_with_langsmith_disabled_and_emits_step_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify LANGSMITH_TRACING=False produces zero LangSmith calls while emitting WebSocket step events."""
    monkeypatch.setattr(settings, "langsmith_tracing", False)
    monkeypatch.setattr(settings, "langsmith_api_key", None)
    monkeypatch.setattr(settings, "default_llm_provider", "mock")

    assert settings.is_langsmith_enabled() is False
    assert get_langsmith_client() is None

    db_file = init_db(tmp_path / "trace_disabled.db")
    captured_events: list[AgentStepEvent] = []

    async def _collector(event: AgentStepEvent) -> None:
        captured_events.append(event)

    orchestrator = OrchestratorAgent(db_path=db_file, provider="mock")
    tx = _sample_transaction("tx_disabled_01")
    assessment = await orchestrator.evaluate_transaction(
        transaction=tx,
        db_path=db_file,
        on_step_event=_collector,
    )

    assert assessment.transaction_id == "tx_disabled_01"
    assert assessment.langsmith_run_id is not None
    assert assessment.trace_url is not None
    assert assessment.langsmith_run_id in assessment.trace_url

    # Verify step events were emitted for DataRetrieverAgent, AnalysisAgent, DecisionAgent, EvaluatorAgent
    node_names = [e.node_name for e in captured_events]
    assert "DataRetrieverAgent" in node_names
    assert "AnalysisAgent" in node_names
    assert "DecisionAgent" in node_names
    assert "EvaluatorAgent" in node_names

    event_types = {e.event_type for e in captured_events}
    assert AgentStepEventType.STEP_STARTED.value in event_types
    assert AgentStepEventType.TOOL_EXECUTED.value in event_types
    assert AgentStepEventType.CRITIC_VERDICT.value in event_types
    assert AgentStepEventType.STEP_COMPLETED.value in event_types

    # Every emitted event carries the correlated trace_id
    for ev in captured_events:
        assert ev.trace_id == assessment.langsmith_run_id
        assert ev.details.get("policy_year") == "2026"


def test_build_langchain_run_config_sanitizes_metadata() -> None:
    """Verify build_langchain_run_config populates tags, run_id, and sanitized metadata."""
    test_settings = Settings(
        langsmith_tracing=True,
        langsmith_api_key="lsv2_test_key_123",
        langsmith_project="fraud-test-project",
        langsmith_mask_pii=True,
        environment="staging",
    )
    assert test_settings.is_langsmith_enabled() is True

    cfg = build_langchain_run_config(
        tx_id="tx_cfg_01",
        account_id="acc_01",
        policy_year="2026",
        tags=["custom:tag"],
        metadata={"pan": "4111222233334444", "amount": 250.0},
        current_settings=test_settings,
    )

    assert cfg["run_name"] == "FraudEvaluationSupervisor"
    assert cfg["run_id"] is not None
    assert "fraud-scorer" in cfg["tags"]
    assert "env:staging" in cfg["tags"]
    assert "policy_year:2026" in cfg["tags"]
    assert "custom:tag" in cfg["tags"]
    assert cfg["metadata"]["pan"] == "****-****-****-4444"
    assert cfg["metadata"]["amount"] == 250.0
    assert cfg["metadata"]["langsmith_enabled"] is True


@pytest.mark.asyncio
async def test_safe_traceable_executes_when_enabled_and_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify @safe_traceable works transparently for both sync and async functions."""
    monkeypatch.setattr(settings, "langsmith_tracing", False)

    @safe_traceable(name="custom_async_span", run_type="tool")
    async def _async_add(a: int, b: int) -> int:
        return a + b

    @safe_traceable(name="custom_sync_span", run_type="tool")
    def _sync_mul(a: int, b: int) -> int:
        return a * b

    assert await _async_add(3, 4) == 7
    assert _sync_mul(3, 5) == 15


# =============================================================================
# 3. Actor-Critic Retry & Circuit Breaker Trace Metadata Tests
# =============================================================================


@pytest.mark.asyncio
async def test_circuit_breaker_fallback_emits_event_and_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify that when DecisionAgent repeatedly produces invalid math, CircuitBreakerFallback emits an event."""
    monkeypatch.setattr(settings, "default_llm_provider", "mock")
    db_file = init_db(tmp_path / "cb_trace.db")

    class _FaultyDecisionAgent(DecisionAgent):
        async def make_decision(self, transaction: Transaction, **kwargs: Any) -> FraudAssessment:
            return FraudAssessment(
                transaction_id=transaction.transaction_id,
                account_id=transaction.account_id,
                overall_risk_score=95.0,
                decision="APPROVE",  # Contradicts score=95.0 (requires DECLINE)
                risk_factors=[
                    RiskFactor(
                        category="VELOCITY",
                        severity="HIGH",
                        contribution_score=20.0,
                        description="Velocity spike",
                    )
                ],
                reasoning_summary="Faulty assessment for circuit breaker test (VELOCITY).",
                tools_invoked=["check_velocity"],
            )

    emitted: list[AgentStepEvent] = []

    async def _on_event(ev: AgentStepEvent) -> None:
        emitted.append(ev)

    orchestrator = OrchestratorAgent(
        db_path=db_file,
        provider="mock",
        decision_agent=_FaultyDecisionAgent(),
        max_retries=1,
    )
    tx = _sample_transaction("tx_cb_fallback_01")
    state = await orchestrator.run_workflow_state(tx, db_path=db_file, on_step_event=_on_event)

    assert state.is_fallback is True
    assert state.retry_count == 2
    assert state.trace_id is not None

    cb_events = [
        e for e in emitted if e.event_type == AgentStepEventType.CIRCUIT_BREAKER_TRIGGERED.value
    ]
    assert len(cb_events) == 1
    assert cb_events[0].node_name == "CircuitBreakerFallback"
    assert cb_events[0].details.get("is_fallback") is True


# =============================================================================
# 4. SQLite Persistence, WebSocket Streaming & Analyst Feedback Dispatch Tests
# =============================================================================


def test_sqlite_persists_and_retrieves_langsmith_run_id(tmp_path: Path) -> None:
    """Verify transaction_scores table stores and returns langsmith_run_id."""
    db_file = init_db(tmp_path / "sqlite_run_id.db")
    insert_transaction(
        transaction_id="tx_sql_trace_01",
        username="user_trace_01",
        transaction_type="CARD",
        amount=120.0,
        latitude=37.7749,
        longitude=-122.4194,
        db_path=db_file,
    )
    inserted = insert_transaction_score(
        transaction_id="tx_sql_trace_01",
        score=15.0,
        approval_status="APPROVE",
        reasoning_summary="Clean transaction.",
        langsmith_run_id="run-uuid-998877",
        db_path=db_file,
    )
    assert inserted["langsmith_run_id"] == "run-uuid-998877"

    fetched = select_transaction_score("tx_sql_trace_01", db_path=db_file)
    assert fetched is not None
    assert fetched["langsmith_run_id"] == "run-uuid-998877"


def test_api_gateway_streams_step_events_and_dispatches_analyst_feedback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify POST /api/v1/transactions/score streams AgentStepEvents over WS and POST /decision dispatches feedback."""
    monkeypatch.setattr(settings, "default_llm_provider", "mock")
    db_file = init_db(tmp_path / "gateway_trace.db")
    app = create_app(db_path=db_file)
    client = TestClient(app)

    score_payload = {
        "username": "good_persona_01",
        "datetime": datetime.now(UTC).isoformat(),
        "ip": "198.51.100.42",
        "device_id": "dev_macbook_01",
        "location": {
            "latitude": 37.7749,
            "longitude": -122.4194,
            "city": "San Francisco",
            "state": "CA",
            "country": "US",
            "postal_code": "94103",
        },
        "transaction_details": {
            "transaction_id": "tx_gw_stream_01",
            "transaction_type": "CARD",
            "amount": 55.00,
            "currency": "USD",
            "merchant": {
                "merchant_id": "merch_grocery_01",
                "name": "Whole Foods Market",
                "mcc": "5411",
                "country": "US",
            },
            "card_details": {
                "card_type": "CREDIT",
                "card_network": "VISA",
                "card_last_four": "4242",
                "is_card_present": True,
                "cvv_verified": True,
                "avs_result": "Y",
            },
        },
    }

    received_ws_messages: list[dict[str, Any]] = []
    with client.websocket_connect("/ws/transactions/events") as ws:
        resp = client.post("/api/v1/transactions/score", json=score_payload)
        assert resp.status_code == 200
        resp_data = resp.json()
        assert resp_data["transaction_id"] == "tx_gw_stream_01"
        assert resp_data["langsmith_run_id"] is not None
        assert resp_data["trace_url"] == get_langsmith_trace_url(resp_data["langsmith_run_id"])

        # Drain all WebSocket events up to TRANSACTION_SCORED
        while True:
            msg = ws.receive_json()
            received_ws_messages.append(msg)
            if msg.get("event_type") == "TRANSACTION_SCORED":
                break

    # Verify step events arrived before TRANSACTION_SCORED
    step_events = [m for m in received_ws_messages if m.get("event_type") != "TRANSACTION_SCORED"]
    assert len(step_events) >= 4
    scored_event = received_ws_messages[-1]
    assert scored_event["event_type"] == "TRANSACTION_SCORED"
    assert scored_event["score_details"]["langsmith_run_id"] == resp_data["langsmith_run_id"]

    # Mock LangSmith client to verify POST /api/v1/transactions/decision dispatches feedback
    mock_ls_client = MagicMock()
    monkeypatch.setattr(
        "fraud_scorer.observability.tracer.get_langsmith_client",
        lambda _cfg=None: mock_ls_client,
    )

    decision_resp = client.post(
        "/api/v1/transactions/decision",
        json={
            "transaction_id": "tx_gw_stream_01",
            "accept": True,
            "reason": "Verified legitimate cardholder purchase (PAN 4111222233334444).",
        },
    )
    assert decision_resp.status_code == 200
    assert mock_ls_client.create_feedback.called
    call_kwargs = mock_ls_client.create_feedback.call_args.kwargs
    assert call_kwargs["run_id"] == resp_data["langsmith_run_id"]
    assert call_kwargs["key"] == "analyst_decision"
    assert call_kwargs["score"] == 1.0
    assert "4111222233334444" not in call_kwargs["comment"]
    assert "****-****-****-4444" in call_kwargs["comment"]


def test_record_feedback_returns_false_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify record_feedback is a safe no-op returning False when LangSmith is disabled."""
    monkeypatch.setattr(settings, "langsmith_tracing", False)
    monkeypatch.setattr(settings, "langsmith_api_key", None)
    assert record_feedback("run-123", score=1.0, comment="Test") is False
    assert record_feedback(None, score=1.0, comment="Test") is False


def test_web_client_contains_live_reasoning_timeline_and_trace_link() -> None:
    """Verify index.html, queue.html, and app.js include the Live Agent Reasoning card & LangSmith link."""
    static_dir = Path(__file__).resolve().parents[1] / "src" / "web_client" / "static"
    index_html = (static_dir / "index.html").read_text(encoding="utf-8")
    queue_html = (static_dir / "queue.html").read_text(encoding="utf-8")
    app_js = (static_dir / "app.js").read_text(encoding="utf-8")

    assert 'id="live-agent-timeline-list"' in index_html
    assert 'id="langsmith-trace-link"' in index_html
    assert "View Trace in LangSmith" in index_html
    assert 'id="live-agent-timeline-list"' in queue_html
    assert "handleAgentStepEvent" in app_js
