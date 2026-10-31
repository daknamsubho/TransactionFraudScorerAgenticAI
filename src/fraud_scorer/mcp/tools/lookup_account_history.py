"""MCP Tool: lookup_account_history — Retrieve historical account age, disputes, and average spend."""

from typing import Any

from fraud_scorer.mcp.tools.mock_db import get_account_profile


def lookup_account_history(account_id: str) -> dict[str, Any]:
    """Retrieve historical account age, chargeback history, and average transaction amount.

    Args:
        account_id: Customer account identifier.

    Returns:
        Dictionary with account_age_days, prior_disputes, avg_transaction_amount, trust_tier, and risk score.
    """
    account_info = get_account_profile(account_id)
    age_days = int(account_info.get("account_age_days", 180))
    chargebacks = int(account_info.get("chargeback_count", 0))
    avg_spend = float(account_info.get("avg_spend", 100.0))
    trust_tier = str(account_info.get("trust_tier", "standard"))

    if chargebacks >= 2 or (age_days < 7 and trust_tier == "untrusted"):
        score = 85.0
        reason = f"High risk account: new account ({age_days} days old) with {chargebacks} prior dispute(s)."
    elif age_days < 14:
        score = 40.0
        reason = f"New account profile: {age_days} days since registration."
    else:
        score = 5.0
        reason = f"Established account: {age_days} days active, {chargebacks} prior dispute(s)."

    return {
        "account_id": account_id,
        # Architecture contract fields
        "account_age_days": age_days,
        "prior_disputes": chargebacks,
        "avg_transaction_amount": avg_spend,
        # Orchestrator / legacy compatibility fields
        "chargeback_count": chargebacks,
        "trust_tier": trust_tier,
        "account_risk_score": score,
        "reasoning": reason,
    }
