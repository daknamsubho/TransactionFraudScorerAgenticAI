"""CRUD functions (SELECT, INSERT, UPDATE, DELETE) and dynamic profile metric calculations."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqllite.database import DEFAULT_DB_PATH, get_connection, init_db
from sqllite.queries import (
    DELETE_TRANSACTION_SCORE_SQL,
    DELETE_TRANSACTION_SQL,
    DELETE_USER_PROFILE_SQL,
    INSERT_TRANSACTION_SCORE_SQL,
    INSERT_TRANSACTION_SQL,
    SELECT_ALL_USER_PROFILES_SQL,
    SELECT_TRANSACTION_BY_ID_SQL,
    SELECT_TRANSACTION_SCORE_BY_TX_ID_SQL,
    SELECT_TRANSACTION_WITH_SCORE_BY_TX_ID_SQL,
    SELECT_TRANSACTIONS_BY_STATUS_SQL,
    SELECT_TRANSACTIONS_BY_USERNAME_SQL,
    SELECT_USER_PROFILE_BY_USERNAME_SQL,
    SELECT_USER_TRANSACTION_STATS_SQL,
    UPDATE_TRANSACTION_DECISION_SQL,
    UPDATE_TRANSACTION_SCORE_SQL,
    UPDATE_TRANSACTION_STATUS_SQL,
    UPDATE_USER_PROFILE_SQL,
    UPSERT_USER_PROFILE_SQL,
)


def _now_iso() -> str:
    """Return current UTC timestamp in ISO-8601 format."""
    return datetime.now(UTC).isoformat()


# =============================================================================
# 1. UserProfile CRUD Operations
# =============================================================================


def insert_user_profile(
    username: str,
    created_date: str | None = None,
    address: str | None = None,
    city: str | None = None,
    state: str | None = None,
    country: str = "US",
    postal_code: str | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    """Insert or upsert a UserProfile record into user_profiles."""
    init_db(db_path)
    now = _now_iso()
    params = {
        "username": username,
        "created_date": created_date or now,
        "address": address,
        "city": city,
        "state": state,
        "country": country,
        "postal_code": postal_code,
        "updated_at": now,
    }
    with get_connection(db_path) as conn:
        conn.execute(UPSERT_USER_PROFILE_SQL, params)
        conn.commit()
    result = select_user_profile(username, db_path=db_path)
    return result or params


def select_user_profile(
    username: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any] | None:
    """Select a single UserProfile record by username."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        row = conn.execute(SELECT_USER_PROFILE_BY_USERNAME_SQL, {"username": username}).fetchone()
        return dict(row) if row is not None else None


def select_all_user_profiles(
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    """Select all UserProfile records ordered by created_date descending."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        rows = conn.execute(SELECT_ALL_USER_PROFILES_SQL).fetchall()
        return [dict(row) for row in rows]


def update_user_profile(
    username: str,
    address: str | None = None,
    city: str | None = None,
    state: str | None = None,
    country: str = "US",
    postal_code: str | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any] | None:
    """Update address fields on an existing UserProfile record."""
    init_db(db_path)
    params = {
        "username": username,
        "address": address,
        "city": city,
        "state": state,
        "country": country,
        "postal_code": postal_code,
        "updated_at": _now_iso(),
    }
    with get_connection(db_path) as conn:
        conn.execute(UPDATE_USER_PROFILE_SQL, params)
        conn.commit()
    return select_user_profile(username, db_path=db_path)


def delete_user_profile(
    username: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> bool:
    """Delete a UserProfile record by username (cascades to transactions and scores)."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        cursor = conn.execute(DELETE_USER_PROFILE_SQL, {"username": username})
        conn.commit()
        return cursor.rowcount > 0


# =============================================================================
# 2. Transaction CRUD Operations
# =============================================================================


def _deserialize_transaction_row(row_dict: dict[str, Any]) -> dict[str, Any]:
    """Normalize boolean and JSON fields in a transaction row dictionary."""
    result = dict(row_dict)
    result["is_card_present"] = bool(result.get("is_card_present", 0))
    raw_details = result.get("payment_details_json")
    if isinstance(raw_details, str) and raw_details:
        try:
            result["payment_details"] = json.loads(raw_details)
        except json.JSONDecodeError:
            result["payment_details"] = {}
    else:
        result["payment_details"] = {}
    return result


def insert_transaction(
    transaction_id: str,
    username: str,
    transaction_type: str,
    amount: float,
    latitude: float,
    longitude: float,
    currency: str = "USD",
    timestamp: str | None = None,
    ip_address: str | None = None,
    device_id: str | None = None,
    city: str | None = None,
    state: str | None = None,
    country: str = "US",
    postal_code: str | None = None,
    merchant_id: str | None = None,
    merchant_name: str | None = None,
    mcc: str | None = None,
    merchant_country: str = "US",
    payment_method_type: str | None = None,
    card_or_account_last_four: str | None = None,
    is_card_present: bool = False,
    payment_details: dict[str, Any] | None = None,
    status: str = "REVIEW",
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    """Insert a Transaction record into transactions (ensuring user_profile exists)."""
    init_db(db_path)
    if select_user_profile(username, db_path=db_path) is None:
        insert_user_profile(
            username=username,
            city=city,
            state=state,
            country=country,
            postal_code=postal_code,
            db_path=db_path,
        )

    now = _now_iso()
    params = {
        "transaction_id": transaction_id,
        "username": username,
        "transaction_type": transaction_type.upper(),
        "amount": float(amount),
        "currency": currency.upper(),
        "timestamp": timestamp or now,
        "ip_address": ip_address,
        "device_id": device_id,
        "latitude": float(latitude),
        "longitude": float(longitude),
        "city": city,
        "state": state,
        "country": country.upper(),
        "postal_code": postal_code,
        "merchant_id": merchant_id,
        "merchant_name": merchant_name,
        "mcc": mcc,
        "merchant_country": merchant_country.upper(),
        "payment_method_type": payment_method_type,
        "card_or_account_last_four": card_or_account_last_four,
        "is_card_present": 1 if is_card_present else 0,
        "payment_details_json": json.dumps(payment_details or {}),
        "status": status,
        "created_at": now,
        "updated_at": now,
    }
    with get_connection(db_path) as conn:
        conn.execute(INSERT_TRANSACTION_SQL, params)
        conn.commit()
    tx = select_transaction(transaction_id, db_path=db_path)
    return tx or _deserialize_transaction_row(params)


def select_transaction(
    transaction_id: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any] | None:
    """Select a single Transaction record by transaction_id."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        row = conn.execute(SELECT_TRANSACTION_BY_ID_SQL, {"transaction_id": transaction_id}).fetchone()
        return _deserialize_transaction_row(dict(row)) if row is not None else None


def select_transactions_by_username(
    username: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    """Select all Transaction records for a username ordered by timestamp descending."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        rows = conn.execute(SELECT_TRANSACTIONS_BY_USERNAME_SQL, {"username": username}).fetchall()
        return [_deserialize_transaction_row(dict(row)) for row in rows]


def select_transactions_by_status(
    status: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    """Select all Transaction records matching a given status."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        rows = conn.execute(SELECT_TRANSACTIONS_BY_STATUS_SQL, {"status": status}).fetchall()
        return [_deserialize_transaction_row(dict(row)) for row in rows]


def update_transaction_status(
    transaction_id: str,
    status: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any] | None:
    """Update the status and updated_at timestamp of a Transaction record."""
    init_db(db_path)
    params = {
        "transaction_id": transaction_id,
        "status": status,
        "updated_at": _now_iso(),
    }
    with get_connection(db_path) as conn:
        conn.execute(UPDATE_TRANSACTION_STATUS_SQL, params)
        conn.commit()
    return select_transaction(transaction_id, db_path=db_path)


def delete_transaction(
    transaction_id: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> bool:
    """Delete a Transaction record by transaction_id (cascades to transaction_scores)."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        cursor = conn.execute(DELETE_TRANSACTION_SQL, {"transaction_id": transaction_id})
        conn.commit()
        return cursor.rowcount > 0


# =============================================================================
# 3. Transaction Scores & Dispositions CRUD Operations
# =============================================================================


def _deserialize_score_row(row_dict: dict[str, Any]) -> dict[str, Any]:
    """Normalize JSON and boolean fields in a transaction_scores row dictionary."""
    result = dict(row_dict)
    raw_accepted = result.get("decision_accepted")
    if raw_accepted is not None:
        result["decision_accepted"] = bool(raw_accepted)

    raw_factors = result.get("risk_factors_json")
    if isinstance(raw_factors, str) and raw_factors:
        try:
            result["risk_factors"] = json.loads(raw_factors)
        except json.JSONDecodeError:
            result["risk_factors"] = []
    else:
        result["risk_factors"] = []

    raw_tools = result.get("tools_invoked_json")
    if isinstance(raw_tools, str) and raw_tools:
        try:
            result["tools_invoked"] = json.loads(raw_tools)
        except json.JSONDecodeError:
            result["tools_invoked"] = []
    else:
        result["tools_invoked"] = []

    return result


def insert_transaction_score(
    transaction_id: str,
    score: float,
    approval_status: str,
    reasoning_summary: str,
    assessment_id: str | None = None,
    decision_accepted: bool | None = None,
    decision_reason: str | None = None,
    risk_factors: list[dict[str, Any]] | None = None,
    tools_invoked: list[str] | None = None,
    evaluated_at: str | None = None,
    decided_at: str | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    """Insert a fraud score and approval status record into transaction_scores."""
    init_db(db_path)
    now = _now_iso()
    db_accepted: int | None = None
    if decision_accepted is not None:
        db_accepted = 1 if decision_accepted else 0

    params = {
        "assessment_id": assessment_id or f"asmt_{uuid4().hex[:12]}",
        "transaction_id": transaction_id,
        "score": float(score),
        "approval_status": approval_status,
        "decision_accepted": db_accepted,
        "decision_reason": decision_reason,
        "reasoning_summary": reasoning_summary,
        "risk_factors_json": json.dumps(risk_factors or []),
        "tools_invoked_json": json.dumps(tools_invoked or []),
        "evaluated_at": evaluated_at or now,
        "decided_at": decided_at,
    }
    with get_connection(db_path) as conn:
        conn.execute(INSERT_TRANSACTION_SCORE_SQL, params)
        conn.commit()
    score_row = select_transaction_score(transaction_id, db_path=db_path)
    return score_row or _deserialize_score_row(params)


def select_transaction_score(
    transaction_id: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any] | None:
    """Select a TransactionScore record by transaction_id."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        row = conn.execute(SELECT_TRANSACTION_SCORE_BY_TX_ID_SQL, {"transaction_id": transaction_id}).fetchone()
        return _deserialize_score_row(dict(row)) if row is not None else None


def select_transaction_with_score(
    transaction_id: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any] | None:
    """Select a joined Transaction + TransactionScore record by transaction_id."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        row = conn.execute(SELECT_TRANSACTION_WITH_SCORE_BY_TX_ID_SQL, {"transaction_id": transaction_id}).fetchone()
        if row is None:
            return None
        merged = _deserialize_transaction_row(dict(row))
        return _deserialize_score_row(merged)


def update_transaction_score(
    transaction_id: str,
    score: float,
    approval_status: str,
    reasoning_summary: str,
    decision_accepted: bool | None = None,
    decision_reason: str | None = None,
    risk_factors: list[dict[str, Any]] | None = None,
    tools_invoked: list[str] | None = None,
    decided_at: str | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any] | None:
    """Update a TransactionScore record by transaction_id."""
    init_db(db_path)
    db_accepted: int | None = None
    if decision_accepted is not None:
        db_accepted = 1 if decision_accepted else 0

    params = {
        "transaction_id": transaction_id,
        "score": float(score),
        "approval_status": approval_status,
        "decision_accepted": db_accepted,
        "decision_reason": decision_reason,
        "reasoning_summary": reasoning_summary,
        "risk_factors_json": json.dumps(risk_factors or []),
        "tools_invoked_json": json.dumps(tools_invoked or []),
        "decided_at": decided_at,
    }
    with get_connection(db_path) as conn:
        conn.execute(UPDATE_TRANSACTION_SCORE_SQL, params)
        conn.commit()
    return select_transaction_score(transaction_id, db_path=db_path)


def update_transaction_decision(
    transaction_id: str,
    accepted: bool,
    reason: str | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any] | None:
    """Update analyst Accept/Reject decision on both transactions and transaction_scores."""
    init_db(db_path)
    new_status = "ACCEPTED" if accepted else "REJECTED"
    now = _now_iso()
    with get_connection(db_path) as conn:
        conn.execute(
            UPDATE_TRANSACTION_STATUS_SQL,
            {"transaction_id": transaction_id, "status": new_status, "updated_at": now},
        )
        conn.execute(
            UPDATE_TRANSACTION_DECISION_SQL,
            {
                "transaction_id": transaction_id,
                "approval_status": new_status,
                "decision_accepted": 1 if accepted else 0,
                "decision_reason": reason,
                "decided_at": now,
            },
        )
        conn.commit()
    return select_transaction_with_score(transaction_id, db_path=db_path)


def delete_transaction_score(
    transaction_id: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> bool:
    """Delete a TransactionScore record by transaction_id."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        cursor = conn.execute(DELETE_TRANSACTION_SCORE_SQL, {"transaction_id": transaction_id})
        conn.commit()
        return cursor.rowcount > 0


# =============================================================================
# 4. Dynamic Metric Calculation for MCP Tools (lookup_account_history)
# =============================================================================


def calculate_user_profile_metrics(
    username: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any] | None:
    """Dynamically calculate account_age_days, prior_disputes, avg_transaction_amount, and trust_tier.

    Per PRD-005, these fields are NOT stored in user_profiles; they are computed dynamically
    from user_profiles.created_date and historical records in transactions + transaction_scores.
    """
    profile = select_user_profile(username, db_path=db_path)
    if profile is None:
        return None

    created_str = str(profile.get("created_date", ""))
    try:
        created_dt = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
        if created_dt.tzinfo is None:
            created_dt = created_dt.replace(tzinfo=UTC)
        age_days = max(0, (datetime.now(UTC) - created_dt).days)
    except ValueError:
        age_days = 180

    with get_connection(db_path) as conn:
        stats_row = conn.execute(SELECT_USER_TRANSACTION_STATS_SQL, {"username": username}).fetchone()

    total_tx = int(stats_row["total_transactions"] or 0) if stats_row else 0
    avg_amount = float(stats_row["avg_transaction_amount"] or 100.0) if stats_row else 100.0
    prior_disputes = int(stats_row["prior_disputes"] or 0) if stats_row else 0

    if prior_disputes >= 2 or age_days < 7:
        trust_tier = "untrusted"
    elif age_days >= 365 and prior_disputes == 0:
        trust_tier = "vip"
    else:
        trust_tier = "standard"

    return {
        "username": username,
        "account_age_days": age_days,
        "prior_disputes": prior_disputes,
        "avg_transaction_amount": round(avg_amount, 2),
        "total_transactions": total_tx,
        "trust_tier": trust_tier,
        "address": profile.get("address"),
        "created_date": created_str,
    }
