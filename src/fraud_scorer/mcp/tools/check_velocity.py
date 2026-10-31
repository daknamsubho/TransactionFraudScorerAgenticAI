"""MCP Tool: check_velocity — Analyze transaction frequency and burst spend."""

from typing import Any

from fraud_scorer.mcp.tools.mock_db import get_account_profile


def check_velocity(account_id: str, window_minutes: int = 60) -> dict[str, Any]:
    """Analyze transaction frequency and total volume in a recent time window.

    Args:
        account_id: Customer account identifier.
        window_minutes: Time window in minutes to evaluate (default 60).

    Returns:
        Dictionary containing transaction count, volume, velocity score (0-100),
        and burst status matching the MCP tool contract.
    """
    account_info = get_account_profile(account_id)
    tx_count = int(account_info.get("recent_tx_count_1h", 1))
    tx_volume = float(account_info.get("recent_tx_volume_1h", 50.0))

    # Velocity scoring heuristics
    is_burst = tx_count >= 5 or tx_volume >= 2500.0
    if tx_count >= 10:
        score = 90.0
        reason = f"Extreme velocity burst: {tx_count} transactions in {window_minutes}m."
    elif tx_count >= 5:
        score = 65.0
        reason = f"Elevated velocity: {tx_count} transactions in {window_minutes}m."
    elif tx_volume >= 3000.0:
        score = 75.0
        reason = f"Unusually high cumulative volume (${tx_volume:,.2f}) in {window_minutes}m."
    else:
        score = 10.0
        reason = f"Velocity within normal baseline: {tx_count} transactions (${tx_volume:,.2f})."

    return {
        "account_id": account_id,
        "window_minutes": window_minutes,
        # Architecture contract fields
        "count_transactions": tx_count,
        "sum_amount": tx_volume,
        "velocity_score": score,
        "is_burst": is_burst,
        # Orchestrator / legacy compatibility fields
        "transaction_count": tx_count,
        "cumulative_volume": tx_volume,
        "velocity_risk_score": score,
        "reasoning": reason,
    }
