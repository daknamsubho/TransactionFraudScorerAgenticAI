"""MCP Tool: lookup_account_history — Retrieve historical account age, disputes, and average spend."""

from pathlib import Path
from typing import Any

from fraud_scorer.mcp.tools.mock_db import get_account_profile
from sqllite.crud import calculate_user_profile_metrics
from sqllite.database import DEFAULT_DB_PATH


def lookup_account_history(
    account_id: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    """Retrieve historical account age, chargeback history, and average transaction amount.

    Dynamically calculates trust_tier, prior_disputes, and avg_transaction_amount from
    the SQLite RDBMS when the user profile is present, with fallback to mock_db.

    Args:
        account_id: Customer account identifier / username.
        db_path: Optional path to the SQLite database file.

    Returns:
        Dictionary with account_age_days, prior_disputes, avg_transaction_amount, trust_tier, and risk score.
    """
    db_metrics = calculate_user_profile_metrics(account_id, db_path=db_path)
    if db_metrics is not None:
        age_days = int(db_metrics["account_age_days"])
        chargebacks = int(db_metrics["prior_disputes"])
        avg_spend = float(db_metrics["avg_transaction_amount"])
        trust_tier = str(db_metrics["trust_tier"])
        total_tx = int(db_metrics["total_transactions"])
        data_source = "sqlite"
    else:
        account_info = get_account_profile(account_id)
        age_days = int(account_info.get("account_age_days", 180))
        chargebacks = int(account_info.get("chargeback_count", 0))
        avg_spend = float(account_info.get("avg_spend", 100.0))
        trust_tier = str(account_info.get("trust_tier", "standard"))
        total_tx = int(account_info.get("recent_tx_count_1h", 1))
        data_source = "mock_db"

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
        "data_source": data_source,
        "total_transactions": total_tx,
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
