"""MCP Tool: check_merchant_risk — Evaluate Merchant Category Code (MCC) and merchant reputation."""

from typing import Any

from fraud_scorer.mcp.tools.mock_db import HIGH_RISK_MCCS


def check_merchant_risk(merchant_id: str, mcc: str) -> dict[str, Any]:
    """Evaluate risk associated with the merchant and its Merchant Category Code (MCC).

    Args:
        merchant_id: Unique merchant identifier.
        mcc: 4-digit Merchant Category Code (e.g. '7995', '6051', '5411').

    Returns:
        Dictionary with MCC risk analysis, risk_tier, high_risk_category, merchant_reputation, and score.
    """
    category_name = HIGH_RISK_MCCS.get(mcc, "Standard Commercial Category")
    is_high_risk = mcc in HIGH_RISK_MCCS

    if is_high_risk:
        score = 70.0
        risk_tier = "HIGH"
        merchant_reputation = "elevated_risk"
        reason = f"High-risk MCC {mcc} ({category_name}) with elevated chargeback propensity."
    else:
        score = 10.0
        risk_tier = "LOW"
        merchant_reputation = "trusted"
        reason = f"Standard merchant category MCC {mcc} ({category_name})."

    return {
        "merchant_id": merchant_id,
        "mcc": mcc,
        # Architecture contract fields
        "risk_tier": risk_tier,
        "high_risk_category": is_high_risk,
        "merchant_reputation": merchant_reputation,
        # Orchestrator / legacy compatibility fields
        "category_name": category_name,
        "is_high_risk_mcc": is_high_risk,
        "merchant_risk_score": score,
        "reasoning": reason,
    }
