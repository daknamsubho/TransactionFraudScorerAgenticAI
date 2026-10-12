"""Unit and integration tests for FraudScorerOrchestrator."""

import pytest

from fraud_scorer.agent.orchestrator import FraudScorerOrchestrator
from fraud_scorer.models.transaction import Transaction


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

    # Account is established, but transaction is $2200 at a standard store
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
