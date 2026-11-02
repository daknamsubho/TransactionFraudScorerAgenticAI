"""MCP Tool: check_merchant_risk — Evaluate MCC and historical merchant disputes from SQLite RDBMS."""

from pathlib import Path
from typing import Any

from fraud_scorer.mcp.tools.mock_db import HIGH_RISK_MCCS
from sqllite.crud import calculate_merchant_risk_metrics
from sqllite.database import DEFAULT_DB_PATH


def check_merchant_risk(
    merchant_id: str,
    mcc: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    """Evaluate risk associated with the merchant and its Merchant Category Code (MCC).

    Queries the SQLite `transactions` and `transaction_scores` tables for historical
    merchant transaction volume and dispute/rejection rates alongside MCC risk.

    Args:
        merchant_id: Unique merchant identifier.
        mcc: 4-digit Merchant Category Code (e.g. '7995', '6051', '5411').
        db_path: Optional path to the SQLite database file.

    Returns:
        Dictionary with MCC risk analysis, historical dispute metrics, risk_tier,
        high_risk_category, merchant_reputation, and score.
    """
    db_stats = calculate_merchant_risk_metrics(merchant_id, db_path=db_path)
    total_tx = int(db_stats["total_transactions"])
    disputed_tx = int(db_stats["disputed_transactions"])
    dispute_rate = float(db_stats["dispute_rate"])
    avg_amount = float(db_stats["avg_amount"])

    category_name = HIGH_RISK_MCCS.get(mcc, "Standard Commercial Category")
    is_high_risk_mcc = mcc in HIGH_RISK_MCCS
    has_elevated_db_disputes = total_tx >= 2 and dispute_rate >= 0.25

    if is_high_risk_mcc or has_elevated_db_disputes:
        score = 75.0 if (is_high_risk_mcc and has_elevated_db_disputes) else 70.0
        risk_tier = "HIGH"
        merchant_reputation = "elevated_risk"
        if has_elevated_db_disputes:
            reason = (
                f"Elevated merchant risk for {merchant_id} (MCC {mcc}): "
                f"{disputed_tx}/{total_tx} historical transactions disputed ({dispute_rate * 100:.1f}%)."
            )
        else:
            reason = f"High-risk MCC {mcc} ({category_name}) with elevated chargeback propensity."
    else:
        score = 10.0
        risk_tier = "LOW"
        merchant_reputation = "trusted"
        reason = (
            f"Standard merchant category MCC {mcc} ({category_name}); "
            f"{total_tx} historical DB transactions ({disputed_tx} disputed)."
        )

    return {
        "merchant_id": merchant_id,
        "mcc": mcc,
        "data_source": "sqlite" if total_tx > 0 else "mcc_catalog",
        "historical_transactions": total_tx,
        "historical_disputes": disputed_tx,
        "historical_dispute_rate": dispute_rate,
        "historical_avg_amount": avg_amount,
        # Architecture contract fields
        "risk_tier": risk_tier,
        "high_risk_category": is_high_risk_mcc or has_elevated_db_disputes,
        "merchant_reputation": merchant_reputation,
        # Orchestrator / legacy compatibility fields
        "category_name": category_name,
        "is_high_risk_mcc": is_high_risk_mcc,
        "merchant_risk_score": score,
        "reasoning": reason,
    }
