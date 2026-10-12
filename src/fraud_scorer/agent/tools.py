"""LangChain Tool adapters wrapping MCP fraud scoring tools."""

from typing import Any

from langchain_core.tools import BaseTool, tool

from fraud_scorer.mcp.tools.risk_tools import (
    check_geo_anomaly,
    check_merchant_risk,
    check_velocity,
    lookup_account_history,
)


@tool
def check_velocity_tool(account_id: str, window_minutes: int = 60) -> dict[str, Any]:
    """Analyze transaction velocity, swipe frequency, and burst spend for an account.

    Args:
        account_id: Customer account identifier.
        window_minutes: Time window in minutes to evaluate (default 60).
    """
    return check_velocity(account_id=account_id, window_minutes=window_minutes)


@tool
def check_geo_anomaly_tool(
    account_id: str,
    current_lat: float,
    current_lon: float,
    current_timestamp_iso: str | None = None,
) -> dict[str, Any]:
    """Detect impossible travel, extreme distances, and rapid geographic hops between transactions.

    Args:
        account_id: Customer account identifier.
        current_lat: Current transaction latitude (-90.0 to 90.0).
        current_lon: Current transaction longitude (-180.0 to 180.0).
        current_timestamp_iso: ISO-8601 timestamp string of the current transaction.
    """
    return check_geo_anomaly(
        account_id=account_id,
        current_lat=current_lat,
        current_lon=current_lon,
        current_timestamp_iso=current_timestamp_iso,
    )


@tool
def check_merchant_risk_tool(merchant_id: str, mcc: str) -> dict[str, Any]:
    """Evaluate Merchant Category Code (MCC) risk and commercial reputation.

    Args:
        merchant_id: Merchant identifier.
        mcc: 4-digit Merchant Category Code (e.g. '7995', '6051', '5411').
    """
    return check_merchant_risk(merchant_id=merchant_id, mcc=mcc)


@tool
def lookup_account_history_tool(account_id: str) -> dict[str, Any]:
    """Retrieve historical account age, chargeback history, and trust profile.

    Args:
        account_id: Customer account identifier.
    """
    return lookup_account_history(account_id=account_id)


def get_langchain_fraud_tools() -> list[BaseTool]:
    """Return all LangChain tool adapters for MCP fraud scoring."""
    return [
        check_velocity_tool,
        check_geo_anomaly_tool,
        check_merchant_risk_tool,
        lookup_account_history_tool,
    ]
