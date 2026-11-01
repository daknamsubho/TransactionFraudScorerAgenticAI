"""MCP Tool: check_velocity — Analyze transaction frequency and burst spend from SQLite RDBMS."""

from pathlib import Path
from typing import Any

from fraud_scorer.mcp.tools.mock_db import get_account_profile
from sqllite.crud import calculate_velocity_metrics
from sqllite.database import DEFAULT_DB_PATH


def check_velocity(
    account_id: str,
    window_minutes: int = 60,
    reference_timestamp: str | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    """Analyze transaction frequency and total volume in a recent time window.

    Queries the SQLite `transactions` table for historical activity when the account
    is present in the database, falling back to `mock_db` otherwise.

    Args:
        account_id: Customer account identifier / username.
        window_minutes: Time window in minutes to evaluate (default 60).
        reference_timestamp: Optional ISO-8601 timestamp anchoring the end of the window.
        db_path: Optional path to the SQLite database file.

    Returns:
        Dictionary containing transaction count, volume, velocity score (0-100),
        and burst status matching the MCP tool contract.
    """
    db_velocity = calculate_velocity_metrics(
        username=account_id,
        window_minutes=window_minutes,
        reference_timestamp=reference_timestamp,
        db_path=db_path,
    )
    if db_velocity is not None:
        tx_count = int(db_velocity["count_transactions"])
        tx_volume = float(db_velocity["sum_amount"])
        data_source = "sqlite"
    else:
        account_info = get_account_profile(account_id)
        tx_count = int(account_info.get("recent_tx_count_1h", 1))
        tx_volume = float(account_info.get("recent_tx_volume_1h", 50.0))
        data_source = "mock_db"

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
        "data_source": data_source,
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
