"""Unit tests for the SQLite RDBMS persistence system (src/sqllite)."""

from pathlib import Path

from fraud_scorer.mcp.tools.lookup_account_history import lookup_account_history
from sqllite import (
    SCHEMA_SQL_PATH,
    calculate_user_profile_metrics,
    delete_transaction,
    delete_transaction_score,
    delete_user_profile,
    get_connection,
    init_db,
    insert_transaction,
    insert_transaction_score,
    insert_user_profile,
    install_and_setup_sqlite,
    select_all_user_profiles,
    select_transaction,
    select_transaction_score,
    select_transaction_with_score,
    select_transactions_by_status,
    select_transactions_by_username,
    select_user_profile,
    update_transaction_decision,
    update_transaction_score,
    update_transaction_status,
    update_user_profile,
)


def test_schema_initialization_and_table_columns(tmp_path: Path) -> None:
    """Verify schema.sql creates the 3 tables and excludes derived columns from user_profiles."""
    assert SCHEMA_SQL_PATH.exists()
    db_file = tmp_path / "test_fraud_scorer.db"
    info = install_and_setup_sqlite(db_file)

    assert db_file.exists()
    assert info["tables"] == ["transaction_scores", "transactions", "user_profiles"]

    with get_connection(db_file) as conn:
        cols_cursor = conn.execute("PRAGMA table_info(user_profiles);")
        user_profile_columns = {str(row["name"]) for row in cols_cursor.fetchall()}

    assert "username" in user_profile_columns
    assert "created_date" in user_profile_columns
    assert "address" in user_profile_columns
    # Per PRD-005 requirement: trust_tier, prior_disputes, and avg_transaction_amount must NOT be in user_profiles
    assert "trust_tier" not in user_profile_columns
    assert "prior_disputes" not in user_profile_columns
    assert "avg_transaction_amount" not in user_profile_columns


def test_user_profile_crud_operations(tmp_path: Path) -> None:
    """Test INSERT, SELECT, UPDATE, and DELETE on user_profiles."""
    db_file = init_db(tmp_path / "crud_users.db")

    # INSERT
    inserted = insert_user_profile(
        username="alice_w",
        created_date="2024-05-01T12:00:00+00:00",
        address="742 Evergreen Terrace",
        city="Springfield",
        state="IL",
        country="US",
        postal_code="62701",
        db_path=db_file,
    )
    assert inserted["username"] == "alice_w"
    assert inserted["address"] == "742 Evergreen Terrace"

    # SELECT single & all
    fetched = select_user_profile("alice_w", db_path=db_file)
    assert fetched is not None
    assert fetched["city"] == "Springfield"

    all_profiles = select_all_user_profiles(db_path=db_file)
    assert len(all_profiles) == 1

    # UPDATE
    updated = update_user_profile(
        username="alice_w",
        address="100 Main St Apt 4B",
        city="Chicago",
        state="IL",
        country="US",
        postal_code="60601",
        db_path=db_file,
    )
    assert updated is not None
    assert updated["address"] == "100 Main St Apt 4B"
    assert updated["city"] == "Chicago"

    # DELETE
    assert delete_user_profile("alice_w", db_path=db_file) is True
    assert select_user_profile("alice_w", db_path=db_file) is None
    assert delete_user_profile("alice_w", db_path=db_file) is False


def test_transaction_and_score_crud_operations(tmp_path: Path) -> None:
    """Test INSERT, SELECT, UPDATE, and DELETE on transactions and transaction_scores."""
    db_file = init_db(tmp_path / "crud_tx.db")

    # 1. INSERT Transaction (auto-creates user_profile if not present)
    tx = insert_transaction(
        transaction_id="tx_001",
        username="bob_builder",
        transaction_type="CARD",
        amount=450.00,
        latitude=37.7749,
        longitude=-122.4194,
        city="San Francisco",
        state="CA",
        country="US",
        merchant_id="merch_01",
        merchant_name="Hardware Depot",
        mcc="5251",
        payment_method_type="credit_card",
        card_or_account_last_four="1234",
        is_card_present=True,
        payment_details={"card_network": "VISA", "cvv_verified": True},
        status="REVIEW",
        db_path=db_file,
    )
    assert tx["transaction_id"] == "tx_001"
    assert tx["is_card_present"] is True
    assert tx["payment_details"]["card_network"] == "VISA"

    # 2. SELECT by ID, username, status
    assert select_transaction("tx_001", db_path=db_file) is not None
    assert len(select_transactions_by_username("bob_builder", db_path=db_file)) == 1
    assert len(select_transactions_by_status("REVIEW", db_path=db_file)) == 1

    # 3. UPDATE transaction status
    updated_tx = update_transaction_status("tx_001", "APPROVE", db_path=db_file)
    assert updated_tx is not None
    assert updated_tx["status"] == "APPROVE"

    # 4. INSERT Transaction Score
    score_rec = insert_transaction_score(
        transaction_id="tx_001",
        score=22.5,
        approval_status="APPROVE",
        reasoning_summary="Low risk hardware store purchase.",
        risk_factors=[{"factor_name": "velocity", "severity": "low", "score_contribution": 5.0}],
        tools_invoked=["check_velocity", "lookup_account_history"],
        db_path=db_file,
    )
    assert score_rec["transaction_id"] == "tx_001"
    assert score_rec["score"] == 22.5
    assert len(score_rec["risk_factors"]) == 1

    # 5. UPDATE Transaction Score & Analyst Decision
    updated_score = update_transaction_score(
        transaction_id="tx_001",
        score=55.0,
        approval_status="REVIEW",
        reasoning_summary="Adjusted score after secondary check.",
        risk_factors=[{"factor_name": "geo", "severity": "medium", "score_contribution": 35.0}],
        tools_invoked=["check_geo_anomaly"],
        db_path=db_file,
    )
    assert updated_score is not None
    assert updated_score["score"] == 55.0

    decided = update_transaction_decision(
        transaction_id="tx_001",
        accepted=False,
        reason="Confirmed unauthorized card usage.",
        db_path=db_file,
    )
    assert decided is not None
    assert decided["status"] == "REJECTED"
    assert decided["approval_status"] == "REJECTED"
    assert decided["decision_accepted"] is False
    assert decided["decision_reason"] == "Confirmed unauthorized card usage."

    # 6. DELETE score and transaction
    assert delete_transaction_score("tx_001", db_path=db_file) is True
    assert select_transaction_score("tx_001", db_path=db_file) is None
    assert delete_transaction("tx_001", db_path=db_file) is True
    assert select_transaction_with_score("tx_001", db_path=db_file) is None


def test_dynamic_account_history_calculation_in_mcp_tool(tmp_path: Path) -> None:
    """Verify lookup_account_history dynamically computes metrics from SQLite records."""
    db_file = init_db(tmp_path / "dynamic_metrics.db")

    insert_user_profile(
        username="vip_customer",
        created_date="2023-01-01T00:00:00+00:00",
        address="500 Fifth Ave",
        city="New York",
        state="NY",
        country="US",
        db_path=db_file,
    )

    insert_transaction(
        transaction_id="tx_vip_1",
        username="vip_customer",
        transaction_type="CARD",
        amount=200.0,
        latitude=40.7128,
        longitude=-74.0060,
        status="APPROVE",
        db_path=db_file,
    )
    insert_transaction(
        transaction_id="tx_vip_2",
        username="vip_customer",
        transaction_type="ACH",
        amount=400.0,
        latitude=40.7128,
        longitude=-74.0060,
        status="ACCEPTED",
        db_path=db_file,
    )

    metrics = calculate_user_profile_metrics("vip_customer", db_path=db_file)
    assert metrics is not None
    assert metrics["avg_transaction_amount"] == 300.0
    assert metrics["prior_disputes"] == 0
    assert metrics["trust_tier"] == "vip"
    assert metrics["account_age_days"] >= 365

    tool_result = lookup_account_history("vip_customer", db_path=db_file)
    assert tool_result["avg_transaction_amount"] == 300.0
    assert tool_result["prior_disputes"] == 0
    assert tool_result["trust_tier"] == "vip"
    assert tool_result["account_risk_score"] == 5.0
