"""Deterministic dataset generator (`docs/dataset`) and SQLite RDBMS bulk seeder."""

import argparse
import json
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqllite.database import DEFAULT_DB_PATH, PROJECT_ROOT, get_connection, init_db
from sqllite.queries import UPSERT_USER_PROFILE_SQL

DEFAULT_DATASET_DIR = PROJECT_ROOT / "docs" / "dataset"

_INSERT_OR_REPLACE_TRANSACTION_SQL = """
INSERT OR REPLACE INTO transactions (
    transaction_id,
    username,
    transaction_type,
    amount,
    currency,
    timestamp,
    ip_address,
    device_id,
    latitude,
    longitude,
    city,
    state,
    country,
    postal_code,
    merchant_id,
    merchant_name,
    mcc,
    merchant_country,
    payment_method_type,
    card_or_account_last_four,
    is_card_present,
    payment_details_json,
    status,
    created_at,
    updated_at
) VALUES (
    :transaction_id,
    :username,
    :transaction_type,
    :amount,
    :currency,
    :timestamp,
    :ip_address,
    :device_id,
    :latitude,
    :longitude,
    :city,
    :state,
    :country,
    :postal_code,
    :merchant_id,
    :merchant_name,
    :mcc,
    :merchant_country,
    :payment_method_type,
    :card_or_account_last_four,
    :is_card_present,
    :payment_details_json,
    :status,
    :created_at,
    :updated_at
);
"""

_INSERT_OR_REPLACE_SCORE_SQL = """
INSERT OR REPLACE INTO transaction_scores (
    assessment_id,
    transaction_id,
    score,
    approval_status,
    decision_accepted,
    decision_reason,
    reasoning_summary,
    risk_factors_json,
    tools_invoked_json,
    evaluated_at,
    decided_at
) VALUES (
    :assessment_id,
    :transaction_id,
    :score,
    :approval_status,
    :decision_accepted,
    :decision_reason,
    :reasoning_summary,
    :risk_factors_json,
    :tools_invoked_json,
    :evaluated_at,
    :decided_at
);
"""

_LOCATIONS: list[dict[str, Any]] = [
    {"city": "San Francisco", "state": "CA", "postal_code": "94103", "lat": 37.7749, "lon": -122.4194},
    {"city": "New York", "state": "NY", "postal_code": "10001", "lat": 40.7128, "lon": -74.0060},
    {"city": "Austin", "state": "TX", "postal_code": "78701", "lat": 30.2672, "lon": -97.7431},
    {"city": "Seattle", "state": "WA", "postal_code": "98101", "lat": 47.6062, "lon": -122.3321},
    {"city": "Chicago", "state": "IL", "postal_code": "60601", "lat": 41.8781, "lon": -87.6298},
    {"city": "Denver", "state": "CO", "postal_code": "80202", "lat": 39.7392, "lon": -104.9903},
    {"city": "Boston", "state": "MA", "postal_code": "02108", "lat": 42.3601, "lon": -71.0589},
    {"city": "Miami", "state": "FL", "postal_code": "33131", "lat": 25.7617, "lon": -80.1918},
    {"city": "Atlanta", "state": "GA", "postal_code": "30303", "lat": 33.7490, "lon": -84.3880},
    {"city": "Phoenix", "state": "AZ", "postal_code": "85004", "lat": 33.4484, "lon": -112.0740},
]

_GOOD_MERCHANTS: list[dict[str, str]] = [
    {"merchant_id": "merch_grocery_01", "name": "Whole Foods Market", "mcc": "5411"},
    {"merchant_id": "merch_cafe_02", "name": "Blue Bottle Coffee", "mcc": "5814"},
    {"merchant_id": "merch_fuel_03", "name": "Shell Service Station", "mcc": "5541"},
    {"merchant_id": "merch_pharmacy_04", "name": "Walgreens Pharmacy", "mcc": "5912"},
    {"merchant_id": "merch_retail_05", "name": "Target Store", "mcc": "5311"},
    {"merchant_id": "merch_utility_06", "name": "Pacific Gas & Electric", "mcc": "4900"},
    {"merchant_id": "merch_dining_07", "name": "Sweetgreen Kitchen", "mcc": "5812"},
    {"merchant_id": "merch_books_08", "name": "Powell's City of Books", "mcc": "5942"},
]


def generate_seed_datasets(
    seed: int = 42,
    reference_time: datetime | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Generate deterministic UserProfile, Transaction, and TransactionScore seed datasets.

    Cohorts per PRD-007:
    - 30 good personas (`good_persona_01`..`good_persona_30`) created in the last 1 year
      (215 to 360 days ago so they precede the 7-month transaction history).
    - 10 bad personas (`bad_persona_01`..`bad_persona_10`) created in the last 5 months
      (15 to 150 days ago).
    - 20 good personas (`good_persona_01`..`good_persona_20`) have 10-30 good transactions
      each week for the last 7 months (30 weeks).
    - 5 bad personas (`bad_persona_01`..`bad_persona_05`) have 2-5 good transactions in
      the last 2 weeks (14 days).
    """
    rng = random.Random(seed)
    ref_dt = reference_time or datetime(2026, 10, 31, 18, 0, 0, tzinfo=UTC)

    user_profiles: list[dict[str, Any]] = []
    transactions: list[dict[str, Any]] = []
    transaction_scores: list[dict[str, Any]] = []

    persona_home_loc: dict[str, dict[str, Any]] = {}

    # 1. 30 Good Personas created in the last 1 year (between 215 and 360 days ago)
    for idx in range(1, 31):
        username = f"good_persona_{idx:02d}"
        loc = _LOCATIONS[(idx - 1) % len(_LOCATIONS)]
        persona_home_loc[username] = loc
        days_ago = rng.randint(215, 360)
        created_dt = ref_dt - timedelta(days=days_ago, hours=rng.randint(0, 23))
        created_iso = created_dt.isoformat()
        user_profiles.append(
            {
                "username": username,
                "created_date": created_iso,
                "address": f"{100 + idx * 7} Market Street, Apt {idx}B",
                "city": loc["city"],
                "state": loc["state"],
                "country": "US",
                "postal_code": loc["postal_code"],
                "updated_at": created_iso,
            }
        )

    # 2. 10 Bad Personas created in the last 5 months (between 15 and 150 days ago)
    for idx in range(1, 11):
        username = f"bad_persona_{idx:02d}"
        loc = _LOCATIONS[(idx + 3) % len(_LOCATIONS)]
        persona_home_loc[username] = loc
        days_ago = rng.randint(15, 150)
        created_dt = ref_dt - timedelta(days=days_ago, hours=rng.randint(0, 23))
        created_iso = created_dt.isoformat()
        user_profiles.append(
            {
                "username": username,
                "created_date": created_iso,
                "address": f"{500 + idx * 13} Industrial Way, Unit {idx}",
                "city": loc["city"],
                "state": loc["state"],
                "country": "US",
                "postal_code": loc["postal_code"],
                "updated_at": created_iso,
            }
        )

    tx_counter = 1

    def _build_good_tx_and_score(username: str, tx_dt: datetime) -> tuple[dict[str, Any], dict[str, Any]]:
        nonlocal tx_counter
        tx_id = f"tx_seed_{tx_counter:06d}"
        asmt_id = f"asmt_seed_{tx_counter:06d}"
        tx_counter += 1

        loc = persona_home_loc[username]
        merch = rng.choice(_GOOD_MERCHANTS)
        is_ach = rng.random() < 0.15
        tx_type = "ACH" if is_ach else "CARD"
        amount = round(rng.uniform(12.50, 185.00), 2)
        last_four = f"{(hash(username) % 9000 + 1000):04d}"
        is_card_present = 0 if is_ach else 1
        payment_method_type = "bank_transfer" if is_ach else "credit_card"

        payment_details = (
            {
                "routing_number": "021000021",
                "account_last_four": last_four,
                "account_type": "CHECKING",
                "sec_code": "WEB",
                "direction": "DEBIT",
                "bank_name": "Chase Bank",
            }
            if is_ach
            else {
                "card_type": "CREDIT",
                "card_network": "VISA",
                "card_last_four": last_four,
                "is_card_present": True,
                "cvv_verified": True,
                "avs_result": "Y",
            }
        )

        ts_iso = tx_dt.isoformat()
        score_val = round(rng.uniform(3.0, 18.0), 1)
        tools_list = ["lookup_account_history", "check_velocity", "check_geo_anomaly", "check_merchant_risk"]

        tx_row = {
            "transaction_id": tx_id,
            "username": username,
            "transaction_type": tx_type,
            "amount": amount,
            "currency": "USD",
            "timestamp": ts_iso,
            "ip_address": f"198.51.100.{(hash(username) % 240) + 10}",
            "device_id": f"dev_{username}",
            "latitude": round(float(loc["lat"]) + rng.uniform(-0.01, 0.01), 4),
            "longitude": round(float(loc["lon"]) + rng.uniform(-0.01, 0.01), 4),
            "city": loc["city"],
            "state": loc["state"],
            "country": "US",
            "postal_code": loc["postal_code"],
            "merchant_id": merch["merchant_id"],
            "merchant_name": merch["name"],
            "mcc": merch["mcc"],
            "merchant_country": "US",
            "payment_method_type": payment_method_type,
            "card_or_account_last_four": last_four,
            "is_card_present": is_card_present,
            "payment_details_json": json.dumps(payment_details),
            "status": "APPROVE",
            "created_at": ts_iso,
            "updated_at": ts_iso,
        }

        score_row = {
            "assessment_id": asmt_id,
            "transaction_id": tx_id,
            "score": score_val,
            "approval_status": "APPROVE",
            "decision_accepted": 1,
            "decision_reason": "Routine low-risk transaction within expected velocity and geography.",
            "reasoning_summary": f"Approved routine {tx_type} purchase at {merch['name']} (${amount:.2f}).",
            "risk_factors_json": "[]",
            "tools_invoked_json": json.dumps(tools_list),
            "evaluated_at": ts_iso,
            "decided_at": ts_iso,
        }
        return tx_row, score_row

    # 3. 20 Good Personas: 10-30 good transactions each week for the last 7 months (30 weeks)
    weeks_in_7_months = 30
    for idx in range(1, 21):
        username = f"good_persona_{idx:02d}"
        for week_idx in range(weeks_in_7_months):
            week_end = ref_dt - timedelta(days=week_idx * 7)
            tx_count_this_week = rng.randint(10, 30)
            for _ in range(tx_count_this_week):
                offset_seconds = rng.randint(60, 7 * 86400 - 60)
                tx_dt = week_end - timedelta(seconds=offset_seconds)
                tx_row, score_row = _build_good_tx_and_score(username, tx_dt)
                transactions.append(tx_row)
                transaction_scores.append(score_row)

    # 4. 5 Bad Personas: 2-5 good transactions in the last 2 weeks (14 days)
    for idx in range(1, 6):
        username = f"bad_persona_{idx:02d}"
        tx_count_two_weeks = rng.randint(2, 5)
        for _ in range(tx_count_two_weeks):
            offset_seconds = rng.randint(60, 14 * 86400 - 60)
            tx_dt = ref_dt - timedelta(seconds=offset_seconds)
            tx_row, score_row = _build_good_tx_and_score(username, tx_dt)
            transactions.append(tx_row)
            transaction_scores.append(score_row)

    return {
        "user_profiles": user_profiles,
        "transactions": transactions,
        "transaction_scores": transaction_scores,
    }


def write_datasets_to_disk(
    dataset_dir: str | Path = DEFAULT_DATASET_DIR,
    seed: int = 42,
    reference_time: datetime | None = None,
) -> dict[str, Any]:
    """Generate and write the seed datasets to docs/dataset/*.json."""
    target_dir = Path(dataset_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    datasets = generate_seed_datasets(seed=seed, reference_time=reference_time)

    up_path = target_dir / "user_profiles.json"
    tx_path = target_dir / "transactions.json"
    scores_path = target_dir / "transaction_scores.json"

    up_path.write_text(json.dumps(datasets["user_profiles"], indent=2), encoding="utf-8")
    tx_path.write_text(json.dumps(datasets["transactions"], indent=2), encoding="utf-8")
    scores_path.write_text(json.dumps(datasets["transaction_scores"], indent=2), encoding="utf-8")

    return {
        "dataset_dir": str(target_dir),
        "user_profiles_file": str(up_path),
        "transactions_file": str(tx_path),
        "transaction_scores_file": str(scores_path),
        "user_profiles_count": len(datasets["user_profiles"]),
        "transactions_count": len(datasets["transactions"]),
        "transaction_scores_count": len(datasets["transaction_scores"]),
    }


def seed_database(
    db_path: str | Path = DEFAULT_DB_PATH,
    dataset_dir: str | Path = DEFAULT_DATASET_DIR,
    regenerate: bool = False,
    clear_existing: bool = True,
    seed: int = 42,
    reference_time: datetime | None = None,
) -> dict[str, Any]:
    """Load seed datasets from docs/dataset/ (generating if needed) and bulk-insert into SQLite."""
    target_dir = Path(dataset_dir)
    up_path = target_dir / "user_profiles.json"
    tx_path = target_dir / "transactions.json"
    scores_path = target_dir / "transaction_scores.json"

    if regenerate or not (up_path.exists() and tx_path.exists() and scores_path.exists()):
        write_datasets_to_disk(dataset_dir=target_dir, seed=seed, reference_time=reference_time)

    user_profiles: list[dict[str, Any]] = json.loads(up_path.read_text(encoding="utf-8"))
    transactions: list[dict[str, Any]] = json.loads(tx_path.read_text(encoding="utf-8"))
    transaction_scores: list[dict[str, Any]] = json.loads(scores_path.read_text(encoding="utf-8"))

    resolved_db = init_db(db_path)

    with get_connection(resolved_db) as conn:
        if clear_existing:
            conn.execute("DELETE FROM transaction_scores;")
            conn.execute("DELETE FROM transactions;")
            conn.execute("DELETE FROM user_profiles;")
        conn.executemany(UPSERT_USER_PROFILE_SQL, user_profiles)
        conn.executemany(_INSERT_OR_REPLACE_TRANSACTION_SQL, transactions)
        conn.executemany(_INSERT_OR_REPLACE_SCORE_SQL, transaction_scores)
        conn.commit()

    return {
        "db_path": str(resolved_db),
        "dataset_dir": str(target_dir),
        "user_profiles_seeded": len(user_profiles),
        "transactions_seeded": len(transactions),
        "transaction_scores_seeded": len(transaction_scores),
    }


def main() -> None:
    """CLI entrypoint to generate docs/dataset files and seed src/sqllite/fraud_scorer.db."""
    parser = argparse.ArgumentParser(description="Generate docs/dataset files and seed SQLite RDBMS.")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH), help="Path to SQLite database file.")
    parser.add_argument("--dataset-dir", default=str(DEFAULT_DATASET_DIR), help="Path to docs/dataset directory.")
    parser.add_argument("--regenerate", action="store_true", help="Force regeneration of JSON dataset files.")
    args = parser.parse_args()

    summary = seed_database(
        db_path=args.db_path,
        dataset_dir=args.dataset_dir,
        regenerate=args.regenerate,
    )
    print(f"✅ Datasets saved at: {summary['dataset_dir']}")
    print(f"✅ SQLite DB seeded at: {summary['db_path']}")
    print(
        f"📊 Seeded rows: user_profiles={summary['user_profiles_seeded']}, "
        f"transactions={summary['transactions_seeded']}, "
        f"transaction_scores={summary['transaction_scores_seeded']}"
    )


if __name__ == "__main__":
    main()
