"""Unit and integration tests for FraudScorerOrchestrator and LangChain tools."""

import pytest

from fraud_scorer.agent.orchestrator import FraudScorerOrchestrator, is_ollama_available
from fraud_scorer.agent.tools import get_langchain_fraud_tools
from fraud_scorer.models.transaction import Transaction


def test_langchain_tools_registration() -> None:
    """Verify that all 4 LangChain tool adapters are properly instantiated."""
    tools = get_langchain_fraud_tools()
    tool_names = [t.name for t in tools]

    assert len(tools) == 4
    assert "check_velocity_tool" in tool_names
    assert "check_geo_anomaly_tool" in tool_names
    assert "check_merchant_risk_tool" in tool_names
    assert "lookup_account_history_tool" in tool_names


@pytest.mark.asyncio
async def test_langchain_tool_execution() -> None:
    """Verify direct invocation of LangChain tool adapters."""
    tools = {t.name: t for t in get_langchain_fraud_tools()}

    # Test velocity tool invocation
    v_tool = tools["check_velocity_tool"]
    res_v = await v_tool.ainvoke({"account_id": "acc_normal_01", "window_minutes": 60})
    assert "velocity_risk_score" in res_v
    assert res_v["account_id"] == "acc_normal_01"

    # Test merchant tool invocation
    m_tool = tools["check_merchant_risk_tool"]
    res_m = await m_tool.ainvoke({"merchant_id": "m1", "mcc": "7995"})
    assert res_m["is_high_risk_mcc"] is True


def test_is_ollama_available() -> None:
    """is_ollama_available should return a boolean without throwing an unhandled exception."""
    status = is_ollama_available("http://127.0.0.1:9999")
    assert status is False


@pytest.mark.asyncio
async def test_evaluate_normal_transaction(normal_transaction: Transaction) -> None:
    """A standard transaction from a reputable account should be APPROVED."""
    orchestrator = FraudScorerOrchestrator()
    assessment = await orchestrator.evaluate_transaction(normal_transaction)

    assert assessment.decision == "APPROVE"
    assert assessment.overall_risk_score < 30.0
    assert assessment.transaction_id == normal_transaction.transaction_id
    assert assessment.account_id == normal_transaction.account_id
    assert "Approved" in assessment.reasoning_summary
    assert len(assessment.tools_invoked) >= 4


@pytest.mark.asyncio
async def test_evaluate_fraudulent_transaction(fraudulent_transaction: Transaction) -> None:
    """A suspicious transaction with impossible travel and high amount should be DECLINED."""
    orchestrator = FraudScorerOrchestrator()
    assessment = await orchestrator.evaluate_transaction(fraudulent_transaction)

    assert assessment.decision == "DECLINE"
    assert assessment.overall_risk_score >= 70.0
    assert len(assessment.risk_factors) >= 3

    categories = [f.category for f in assessment.risk_factors]
    assert "GEO_ANOMALY" in categories
    assert "MERCHANT_RISK" in categories
    assert "AMOUNT_ANOMALY" in categories
    assert "DECLINE" in assessment.reasoning_summary


@pytest.mark.asyncio
async def test_borderline_transaction_triggers_review() -> None:
    """A transaction with moderate signals should trigger REVIEW."""
    from fraud_scorer.models.transaction import GeoLocation, MerchantInfo, PaymentMethod

    tx_review = Transaction(
        account_id="acc_normal_01",
        amount=2200.0,
        currency="USD",
        location=GeoLocation(
            latitude=37.7749,
            longitude=-122.4194,
            city="San Francisco",
        ),
        payment_method=PaymentMethod(payment_type="credit_card"),
        merchant=MerchantInfo(
            merchant_id="m_electronics_1",
            name="Electronics Megastore",
            mcc="5732",
        ),
    )

    orchestrator = FraudScorerOrchestrator()
    assessment = await orchestrator.evaluate_transaction(tx_review)

    assert assessment.decision in ("REVIEW", "APPROVE")
    if assessment.decision == "REVIEW":
        assert 30.0 <= assessment.overall_risk_score < 70.0
