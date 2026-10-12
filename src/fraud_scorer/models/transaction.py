"""Domain models for Transaction Fraud Scoring."""

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class GeoLocation(BaseModel):
    """Geographic coordinates and location metadata."""

    latitude: float = Field(..., ge=-90.0, le=90.0, description="Latitude in degrees")
    longitude: float = Field(..., ge=-180.0, le=180.0, description="Longitude in degrees")
    city: str | None = Field(default=None, description="City name if available")
    country: str = Field(default="US", min_length=2, max_length=3, description="ISO country code")


class PaymentMethod(BaseModel):
    """Payment method details."""

    payment_type: Literal["credit_card", "debit_card", "bank_transfer", "crypto", "digital_wallet"] = Field(
        ..., description="Payment method type"
    )
    card_last_four: str | None = Field(default=None, min_length=4, max_length=4, description="Last 4 digits of card")
    is_card_present: bool = Field(default=False, description="Whether the card was physically present")


class MerchantInfo(BaseModel):
    """Merchant identity and categorization."""

    merchant_id: str = Field(..., description="Unique merchant identifier")
    name: str = Field(..., description="Merchant commercial name")
    mcc: str = Field(..., min_length=4, max_length=4, description="Merchant Category Code (MCC)")
    country: str = Field(default="US", description="Merchant country")


class Transaction(BaseModel):
    """Represents a financial transaction submitted for fraud scoring."""

    transaction_id: str = Field(default_factory=lambda: f"tx_{uuid4().hex[:12]}", description="Unique transaction ID")
    account_id: str = Field(..., description="Customer account / user ID")
    amount: float = Field(..., gt=0, description="Transaction amount in specified currency")
    currency: str = Field(default="USD", min_length=3, max_length=3, description="Currency code")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Transaction creation timestamp",
    )
    location: GeoLocation = Field(..., description="Location where transaction originated")
    payment_method: PaymentMethod = Field(..., description="Payment method used")
    merchant: MerchantInfo = Field(..., description="Merchant receiving payment")
    device_id: str | None = Field(default=None, description="Device fingerprint if available")
    ip_address: str | None = Field(default=None, description="IP address of origin")


RiskDecision = Literal["APPROVE", "REVIEW", "DECLINE"]
RiskSeverity = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]


class RiskFactor(BaseModel):
    """An individual risk signal contributing to the fraud evaluation."""

    category: str = Field(
        ...,
        description="Category of the risk factor (e.g. VELOCITY, GEO_ANOMALY, MERCHANT_RISK)",
    )
    severity: RiskSeverity = Field(..., description="Severity level of the factor")
    contribution_score: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="Contribution weight or individual risk score (0-100)",
    )
    description: str = Field(..., description="Human-readable explanation of the finding")
    details: dict[str, Any] = Field(default_factory=dict, description="Raw supporting metrics or evidence")


class FraudAssessment(BaseModel):
    """Comprehensive fraud evaluation result produced by the Agent."""

    assessment_id: str = Field(
        default_factory=lambda: f"assess_{uuid4().hex[:12]}",
        description="Unique assessment ID",
    )
    transaction_id: str = Field(..., description="Target transaction ID")
    account_id: str = Field(..., description="Account ID evaluated")
    overall_risk_score: float = Field(..., ge=0.0, le=100.0, description="Aggregated risk score between 0.0 and 100.0")
    decision: RiskDecision = Field(..., description="Disposition decision: APPROVE, REVIEW, DECLINE")
    risk_factors: list[RiskFactor] = Field(default_factory=list, description="List of detected risk factors")
    reasoning_summary: str = Field(..., description="Explainable rationale summarizing the agent's evaluation")
    tools_invoked: list[str] = Field(default_factory=list, description="Names of MCP tools called during analysis")
    evaluated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Assessment completion timestamp",
    )
