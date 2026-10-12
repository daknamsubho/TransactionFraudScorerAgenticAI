"""Unit tests for transaction and fraud assessment domain models."""

import pytest
from pydantic import ValidationError

from fraud_scorer.models.transaction import (
    FraudAssessment,
    GeoLocation,
    MerchantInfo,
    PaymentMethod,
    RiskFactor,
    Transaction,
)


def test_transaction_creation(normal_transaction: Transaction) -> None:
    """Test valid transaction creation and properties."""
    assert normal_transaction.account_id == "acc_normal_01"
    assert normal_transaction.amount == 55.00
    assert normal_transaction.currency == "USD"
    assert normal_transaction.merchant.mcc == "5411"
    assert normal_transaction.location.city == "San Francisco"


def test_transaction_amount_must_be_positive() -> None:
    """Transaction amount must be strictly positive."""
    with pytest.raises(ValidationError):
        Transaction(
            account_id="acc_1",
            amount=-10.0,
            location=GeoLocation(latitude=0.0, longitude=0.0),
            payment_method=PaymentMethod(payment_type="credit_card"),
            merchant=MerchantInfo(merchant_id="m1", name="Test", mcc="5411"),
        )


def test_invalid_coordinates() -> None:
    """Latitude and longitude bounds must be validated."""
    with pytest.raises(ValidationError):
        GeoLocation(latitude=95.0, longitude=0.0)  # Latitude > 90

    with pytest.raises(ValidationError):
        GeoLocation(latitude=0.0, longitude=190.0)  # Longitude > 180


def test_fraud_assessment_model() -> None:
    """Test FraudAssessment creation and risk factor attachments."""
    factor = RiskFactor(
        category="VELOCITY",
        severity="HIGH",
        contribution_score=80.0,
        description="High frequency burst of transactions",
        details={"tx_count": 8},
    )

    assessment = FraudAssessment(
        transaction_id="tx_123",
        account_id="acc_456",
        overall_risk_score=82.5,
        decision="DECLINE",
        risk_factors=[factor],
        reasoning_summary="Declined due to velocity burst.",
        tools_invoked=["check_velocity"],
    )

    assert assessment.overall_risk_score == 82.5
    assert assessment.decision == "DECLINE"
    assert len(assessment.risk_factors) == 1
    assert assessment.risk_factors[0].category == "VELOCITY"
    assert "check_velocity" in assessment.tools_invoked
