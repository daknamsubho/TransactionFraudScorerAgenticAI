"""Unit tests for modular FastMCP risk tools, server registration, and LangChain binding."""

from pathlib import Path

import pytest
from langchain_ollama import ChatOllama

from fraud_scorer.agent.tools import configure_langchain_with_mcp_tools, get_langchain_fraud_tools
from fraud_scorer.mcp.server import FastMCP, create_server
from fraud_scorer.mcp.tools.check_geo_anomaly import check_geo_anomaly, haversine_distance
from fraud_scorer.mcp.tools.check_merchant_risk import check_merchant_risk
from fraud_scorer.mcp.tools.check_velocity import check_velocity
from fraud_scorer.mcp.tools.lookup_account_history import lookup_account_history
from fraud_scorer.mcp.tools.mock_db import get_account_profile
from sqllite import init_db, insert_transaction, insert_transaction_score, insert_user_profile


def test_modular_tool_files_and_mock_db() -> None:
    """Verify each tool lives in its own dedicated module and MockDB returns account profiles."""
    assert check_velocity.__module__ == "fraud_scorer.mcp.tools.check_velocity"
    assert check_geo_anomaly.__module__ == "fraud_scorer.mcp.tools.check_geo_anomaly"
    assert check_merchant_risk.__module__ == "fraud_scorer.mcp.tools.check_merchant_risk"
    assert lookup_account_history.__module__ == "fraud_scorer.mcp.tools.lookup_account_history"

    profile = get_account_profile("acc_normal_01")
    assert profile["trust_tier"] == "established"


def test_haversine_distance() -> None:
    """Verify distance calculation between known landmarks."""
    # Distance between London (51.5074, -0.1278) and Paris (48.8566, 2.3522) ~ 343 km
    dist = haversine_distance(51.5074, -0.1278, 48.8566, 2.3522)
    assert 340.0 <= dist <= 350.0

    # Distance to identical point is 0
    assert haversine_distance(37.7749, -122.4194, 37.7749, -122.4194) == 0.0


def test_check_velocity_normal() -> None:
    """Normal account velocity should return low risk score and architecture contract keys."""
    result = check_velocity(account_id="acc_normal_01")
    assert result["account_id"] == "acc_normal_01"
    assert result["velocity_risk_score"] <= 20.0
    assert result["velocity_score"] == result["velocity_risk_score"]
    assert result["count_transactions"] == 1
    assert result["sum_amount"] == 45.0
    assert result["is_burst"] is False


def test_check_velocity_burst() -> None:
    """Suspicious account with burst transactions should trigger elevated risk score."""
    result = check_velocity(account_id="acc_suspicious_01")
    assert result["account_id"] == "acc_suspicious_01"
    assert result["velocity_risk_score"] >= 65.0
    assert result["is_burst"] is True


def test_check_geo_anomaly_normal() -> None:
    """Location close to previous activity is normal."""
    result = check_geo_anomaly(
        account_id="acc_normal_01",
        current_lat=37.7749,
        current_lon=-122.4194,
    )
    assert result["geo_risk_score"] <= 15.0
    assert result["impossible_travel"] is False


def test_check_geo_anomaly_impossible_travel() -> None:
    """Location thousands of km away within 15 minutes is impossible travel."""
    result = check_geo_anomaly(
        account_id="acc_suspicious_01",
        current_lat=35.6762,
        current_lon=139.6503,
        timestamp="2026-10-12T11:15:00Z",
    )
    assert result["impossible_travel"] is True
    assert result["geo_risk_score"] >= 90.0
    assert result["distance_km"] > 9000.0


def test_check_merchant_risk_standard() -> None:
    """Standard merchant category code (e.g. 5411) should return low risk."""
    result = check_merchant_risk(merchant_id="m_grocery", mcc="5411")
    assert result["is_high_risk_mcc"] is False
    assert result["high_risk_category"] is False
    assert result["risk_tier"] == "LOW"
    assert result["merchant_reputation"] == "trusted"
    assert result["merchant_risk_score"] <= 20.0


def test_check_merchant_risk_high() -> None:
    """Gambling / crypto merchant categories should return high risk."""
    result = check_merchant_risk(merchant_id="m_casino", mcc="7995")
    assert result["is_high_risk_mcc"] is True
    assert result["high_risk_category"] is True
    assert result["risk_tier"] == "HIGH"
    assert result["merchant_reputation"] == "elevated_risk"
    assert result["merchant_risk_score"] >= 70.0


def test_lookup_account_history() -> None:
    """Account profile lookup returns accurate age, chargebacks, and average transaction amount."""
    normal = lookup_account_history(account_id="acc_normal_01")
    assert normal["trust_tier"] == "established"
    assert normal["chargeback_count"] == 0
    assert normal["prior_disputes"] == 0
    assert normal["avg_transaction_amount"] == 110.0
    assert normal["account_risk_score"] <= 20.0

    suspicious = lookup_account_history(account_id="acc_suspicious_01")
    assert suspicious["trust_tier"] == "untrusted"
    assert suspicious["chargeback_count"] >= 2
    assert suspicious["prior_disputes"] >= 2
    assert suspicious["account_risk_score"] >= 75.0


@pytest.mark.asyncio
async def test_mcp_server_initialization() -> None:
    """FastMCP server instance initializes, lists registered tools, and executes tool calls."""
    server = create_server()
    assert isinstance(server, FastMCP)
    assert server.name == "TransactionFraudScorerMCP"
    tools = await server.list_tools()
    tool_names = [t.name for t in tools]
    assert "check_velocity" in tool_names
    assert "check_geo_anomaly" in tool_names
    assert "check_merchant_risk" in tool_names
    assert "lookup_account_history" in tool_names

    call_res = await server.call_tool("check_merchant_risk", {"merchant_id": "m_test", "mcc": "7995"})
    assert call_res is not None


def test_configure_langchain_with_mcp_tools() -> None:
    """Verify LangChain ChatOllama model binds all 4 FastMCP tools cleanly."""
    llm = ChatOllama(model="llama3.2:3b", temperature=0.0)
    bound_llm = configure_langchain_with_mcp_tools(llm)
    assert bound_llm is not None
    assert len(get_langchain_fraud_tools()) == 4


def test_all_mcp_tools_query_sqlite_database(tmp_path: Path) -> None:
    """Verify check_velocity, check_geo_anomaly, check_merchant_risk, and lookup_account_history query SQLite."""
    db_file = init_db(tmp_path / "tools_db.db")

    insert_user_profile(
        username="db_user_01",
        created_date="2025-01-01T00:00:00+00:00",
        address="100 Main St",
        city="San Francisco",
        state="CA",
        country="US",
        db_path=db_file,
    )

    # Insert 6 transactions within 60 minutes in San Francisco at merch_disputed_99
    for idx in range(1, 7):
        tx_id = f"tx_db_{idx}"
        status = "REJECTED" if idx <= 2 else "APPROVE"
        insert_transaction(
            transaction_id=tx_id,
            username="db_user_01",
            transaction_type="CARD",
            amount=300.0,
            timestamp=f"2026-10-31T12:{idx * 5:02d}:00+00:00",
            latitude=37.7749,
            longitude=-122.4194,
            city="San Francisco",
            state="CA",
            country="US",
            merchant_id="merch_disputed_99",
            merchant_name="Disputed Merchant",
            mcc="5411",
            status=status,
            db_path=db_file,
        )
        insert_transaction_score(
            transaction_id=tx_id,
            score=80.0 if status == "REJECTED" else 10.0,
            approval_status=status,
            decision_accepted=status != "REJECTED",
            reasoning_summary="Seeded test score",
            db_path=db_file,
        )

    # 1. check_velocity against SQLite
    vel = check_velocity("db_user_01", window_minutes=60, db_path=db_file)
    assert vel["data_source"] == "sqlite"
    assert vel["count_transactions"] == 6
    assert vel["sum_amount"] == 1800.0
    assert vel["is_burst"] is True
    assert vel["velocity_score"] >= 65.0

    # 2. check_geo_anomaly against SQLite (Tokyo 15 minutes after San Francisco)
    geo = check_geo_anomaly(
        account_id="db_user_01",
        current_lat=35.6762,
        current_lon=139.6503,
        timestamp="2026-10-31T12:45:00+00:00",
        db_path=db_file,
    )
    assert geo["data_source"] == "sqlite"
    assert geo["impossible_travel"] is True
    assert geo["geo_risk_score"] >= 90.0

    # 3. check_merchant_risk against SQLite (2/6 = 33.3% disputed even on standard MCC 5411)
    merch = check_merchant_risk("merch_disputed_99", "5411", db_path=db_file)
    assert merch["data_source"] == "sqlite"
    assert merch["historical_transactions"] == 6
    assert merch["historical_disputes"] == 2
    assert merch["risk_tier"] == "HIGH"
    assert merch["merchant_risk_score"] >= 70.0

    # 4. lookup_account_history against SQLite
    hist = lookup_account_history("db_user_01", db_path=db_file)
    assert hist["data_source"] == "sqlite"
    assert hist["total_transactions"] == 6
    assert hist["prior_disputes"] == 2
    assert hist["avg_transaction_amount"] == 300.0
    assert hist["trust_tier"] == "untrusted"
