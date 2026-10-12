"""Unit tests for MCP risk tools and server registration."""

import pytest

from fraud_scorer.mcp.server import create_server
from fraud_scorer.mcp.tools.risk_tools import (
    check_geo_anomaly,
    check_merchant_risk,
    check_velocity,
    haversine_distance,
    lookup_account_history,
)


def test_haversine_distance() -> None:
    """Verify distance calculation between known landmarks."""
    # Distance between London (51.5074, -0.1278) and Paris (48.8566, 2.3522) ~ 343 km
    dist = haversine_distance(51.5074, -0.1278, 48.8566, 2.3522)
    assert 340.0 <= dist <= 350.0

    # Distance to identical point is 0
    assert haversine_distance(37.7749, -122.4194, 37.7749, -122.4194) == 0.0


def test_check_velocity_normal() -> None:
    """Normal account velocity should return low risk score."""
    result = check_velocity(account_id="acc_normal_01")
    assert result["account_id"] == "acc_normal_01"
    assert result["velocity_risk_score"] <= 20.0
    assert result["is_burst"] is False


def test_check_velocity_burst() -> None:
    """Suspicious account with burst transactions should trigger elevated risk score."""
    result = check_velocity(account_id="acc_suspicious_01")
    assert result["account_id"] == "acc_suspicious_01"
    assert result["velocity_risk_score"] >= 65.0
    assert result["is_burst"] is True


def test_check_geo_anomaly_normal() -> None:
    """Location close to previous activity is normal."""
    # SF location for acc_normal_01 whose last location was SF
    result = check_geo_anomaly(
        account_id="acc_normal_01",
        current_lat=37.7749,
        current_lon=-122.4194,
    )
    assert result["geo_risk_score"] <= 15.0
    assert result["impossible_travel"] is False


def test_check_geo_anomaly_impossible_travel() -> None:
    """Location thousands of km away within 15 minutes is impossible travel."""
    # acc_suspicious_01 was in London at 11:00Z; transaction in Tokyo at 11:15Z
    result = check_geo_anomaly(
        account_id="acc_suspicious_01",
        current_lat=35.6762,
        current_lon=139.6503,
        current_timestamp_iso="2026-10-12T11:15:00Z",
    )
    assert result["impossible_travel"] is True
    assert result["geo_risk_score"] >= 90.0
    assert result["distance_km"] > 9000.0


def test_check_merchant_risk_standard() -> None:
    """Standard merchant category code (e.g. 5411) should return low risk."""
    result = check_merchant_risk(merchant_id="m_grocery", mcc="5411")
    assert result["is_high_risk_mcc"] is False
    assert result["merchant_risk_score"] <= 20.0


def test_check_merchant_risk_high() -> None:
    """Gambling / crypto merchant categories should return high risk."""
    result = check_merchant_risk(merchant_id="m_casino", mcc="7995")
    assert result["is_high_risk_mcc"] is True
    assert result["merchant_risk_score"] >= 70.0


def test_lookup_account_history() -> None:
    """Account profile lookup returns accurate age and chargeback records."""
    normal = lookup_account_history(account_id="acc_normal_01")
    assert normal["trust_tier"] == "established"
    assert normal["chargeback_count"] == 0
    assert normal["account_risk_score"] <= 20.0

    suspicious = lookup_account_history(account_id="acc_suspicious_01")
    assert suspicious["trust_tier"] == "untrusted"
    assert suspicious["chargeback_count"] >= 2
    assert suspicious["account_risk_score"] >= 75.0


@pytest.mark.asyncio
async def test_mcp_server_initialization() -> None:
    """MCP server instance initializes and provides registered tools."""
    server = create_server()
    assert server.name == "TransactionFraudScorerMCP"
    tools = await server.list_tools()
    tool_names = [t.name for t in tools]
    assert "check_velocity" in tool_names
    assert "check_geo_anomaly" in tool_names
    assert "check_merchant_risk" in tool_names
    assert "lookup_account_history" in tool_names
