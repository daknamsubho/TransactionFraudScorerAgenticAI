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

_BAD_MERCHANTS: list[dict[str, str]] = [
    {"merchant_id": "merch_casino_91", "name": "Royal Flush Online Casino", "mcc": "7995", "country": "JP"},
    {"merchant_id": "merch_crypto_92", "name": "Instant Crypto OTC Exchange", "mcc": "6051", "country": "GB"},
    {"merchant_id": "merch_wire_93", "name": "Global Express Wire Transfer", "mcc": "4829", "country": "NG"},
    {"merchant_id": "merch_tele_94", "name": "Direct Inbound TeleServices", "mcc": "5967", "country": "DE"},
    {"merchant_id": "merch_pawn_95", "name": "Metro Gold & Bullion Exchange", "mcc": "5933", "country": "AU"},
]

_ANOMALY_LOCATIONS: list[dict[str, Any]] = [
    {"city": "Tokyo", "state": "TK", "country": "JP", "postal_code": "100-0001", "lat": 35.6762, "lon": 139.6503},
    {"city": "London", "state": "LND", "country": "GB", "postal_code": "EC1A", "lat": 51.5074, "lon": -0.1278},
    {"city": "Lagos", "state": "LA", "country": "NG", "postal_code": "100001", "lat": 6.5244, "lon": 3.3792},
    {"city": "Frankfurt", "state": "HE", "country": "DE", "postal_code": "60311", "lat": 50.1109, "lon": 8.6821},
    {"city": "Sydney", "state": "NSW", "country": "AU", "postal_code": "2000", "lat": -33.8688, "lon": 151.2093},
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


def generate_test_transactions_dataset(
    seed: int = 42,
    reference_time: datetime | None = None,
) -> list[dict[str, Any]]:
    """Generate 25 UI/API test transactions per PRD-011.

    Composition:
    - 20 transactions from existing personas (mix of 10 good and 10 bad).
    - 5 transactions from completely new personas (`new_persona_01`..`new_persona_05`).
    """
    rng = random.Random(seed + 101)
    ref_dt = reference_time or datetime(2026, 10, 31, 18, 0, 0, tzinfo=UTC)
    seed_data = generate_seed_datasets(seed=seed, reference_time=ref_dt)

    # Track latest transaction timestamp per existing persona for realistic velocity/geo tests
    latest_ts_by_user: dict[str, datetime] = {}
    for tx in seed_data["transactions"]:
        uname = str(tx["username"])
        dt_val = datetime.fromisoformat(str(tx["timestamp"]))
        if uname not in latest_ts_by_user or dt_val > latest_ts_by_user[uname]:
            latest_ts_by_user[uname] = dt_val

    test_transactions: list[dict[str, Any]] = []

    # 1. 10 Good Transactions from Existing Personas (test_tx_01 .. test_tx_10)
    for i in range(1, 11):
        username = f"good_persona_{i:02d}"
        loc = _LOCATIONS[(i - 1) % len(_LOCATIONS)]
        merch = _GOOD_MERCHANTS[(i - 1) % len(_GOOD_MERCHANTS)]
        is_ach = i in (4, 8)
        tx_type = "ACH" if is_ach else "CARD"
        amount = round(24.50 + i * 9.75, 2)
        base_dt = latest_ts_by_user.get(username, ref_dt)
        tx_dt = base_dt + timedelta(hours=6 + i)
        last_four = f"{(hash(username) % 9000 + 1000):04d}"

        tx_details: dict[str, Any] = {
            "transaction_id": f"tx_test_{i:03d}",
            "transaction_type": tx_type,
            "amount": amount,
            "currency": "USD",
            "merchant": {
                "merchant_id": merch["merchant_id"],
                "name": merch["name"],
                "mcc": merch["mcc"],
                "country": "US",
            },
        }
        if is_ach:
            tx_details["ach_details"] = {
                "routing_number": "021000021",
                "account_last_four": last_four,
                "account_type": "CHECKING",
                "sec_code": "WEB",
                "direction": "DEBIT",
                "bank_name": "Chase Bank",
            }
        else:
            tx_details["card_details"] = {
                "card_type": "CREDIT",
                "card_network": "VISA",
                "card_last_four": last_four,
                "is_card_present": True,
                "expiration_month": 8,
                "expiration_year": 2028,
                "cvv_verified": True,
                "avs_result": "Y",
            }

        test_transactions.append(
            {
                "scenario_id": f"test_tx_{i:02d}",
                "persona_group": "existing_persona",
                "transaction_profile": "good",
                "description": (
                    f"Existing persona '{username}' routine {tx_type} purchase at {merch['name']} "
                    f"in home city {loc['city']} (${amount:.2f})."
                ),
                "username": username,
                "datetime": tx_dt.isoformat(),
                "ip": f"198.51.100.{(hash(username) % 240) + 10}",
                "device_id": f"dev_{username}",
                "location": {
                    "latitude": loc["lat"],
                    "longitude": loc["lon"],
                    "city": loc["city"],
                    "state": loc["state"],
                    "country": "US",
                    "postal_code": loc["postal_code"],
                },
                "transaction_details": tx_details,
            }
        )

    # 2. 10 Bad Transactions from Existing Personas (test_tx_11 .. test_tx_20)
    bad_existing_users = [
        "bad_persona_01",
        "bad_persona_02",
        "bad_persona_03",
        "bad_persona_04",
        "bad_persona_05",
        "good_persona_11",
        "good_persona_12",
        "good_persona_13",
        "good_persona_14",
        "good_persona_15",
    ]
    for idx_offset, username in enumerate(bad_existing_users, start=11):
        anom_loc = _ANOMALY_LOCATIONS[(idx_offset - 11) % len(_ANOMALY_LOCATIONS)]
        bad_merch = _BAD_MERCHANTS[(idx_offset - 11) % len(_BAD_MERCHANTS)]
        is_ach = idx_offset in (13, 17, 20)
        tx_type = "ACH" if is_ach else "CARD"
        amount = round(2450.00 + (idx_offset - 10) * 375.00, 2)
        base_dt = latest_ts_by_user.get(username, ref_dt)
        # 12 minutes after last known domestic transaction to trigger impossible travel
        tx_dt = base_dt + timedelta(minutes=12)
        last_four = f"{(hash(username) % 9000 + 1000):04d}"

        tx_details = {
            "transaction_id": f"tx_test_{idx_offset:03d}",
            "transaction_type": tx_type,
            "amount": amount,
            "currency": "USD",
            "merchant": {
                "merchant_id": bad_merch["merchant_id"],
                "name": bad_merch["name"],
                "mcc": bad_merch["mcc"],
                "country": bad_merch["country"],
            },
        }
        if is_ach:
            tx_details["ach_details"] = {
                "routing_number": "021000021",
                "account_last_four": last_four,
                "account_type": "CHECKING",
                "sec_code": "WEB",
                "direction": "DEBIT",
                "bank_name": "Offshore Clearing Bank",
            }
        else:
            tx_details["card_details"] = {
                "card_type": "CREDIT",
                "card_network": "MASTERCARD",
                "card_last_four": last_four,
                "is_card_present": False,
                "expiration_month": 11,
                "expiration_year": 2027,
                "cvv_verified": False,
                "avs_result": "N",
            }

        test_transactions.append(
            {
                "scenario_id": f"test_tx_{idx_offset:02d}",
                "persona_group": "existing_persona",
                "transaction_profile": "bad",
                "description": (
                    f"Existing persona '{username}' suspicious {tx_type} transaction in {anom_loc['city']} "
                    f"at high-risk merchant {bad_merch['name']} (MCC {bad_merch['mcc']}, ${amount:,.2f})."
                ),
                "username": username,
                "datetime": tx_dt.isoformat(),
                "ip": f"203.0.113.{idx_offset * 3}",
                "device_id": f"dev_unrecognized_{idx_offset}",
                "location": {
                    "latitude": anom_loc["lat"],
                    "longitude": anom_loc["lon"],
                    "city": anom_loc["city"],
                    "state": anom_loc["state"],
                    "country": anom_loc["country"],
                    "postal_code": anom_loc["postal_code"],
                },
                "transaction_details": tx_details,
            }
        )

    # 3. 5 Transactions with Completely New Personas (test_tx_21 .. test_tx_25)
    new_persona_specs: list[dict[str, Any]] = [
        {
            "scenario_id": "test_tx_21",
            "username": "new_persona_01",
            "profile": "good",
            "tx_type": "CARD",
            "amount": 38.50,
            "loc": _LOCATIONS[0],
            "country": "US",
            "merch": _GOOD_MERCHANTS[0],
            "card_present": True,
            "desc": "Completely new persona 'new_persona_01' small in-person grocery CARD purchase ($38.50).",
        },
        {
            "scenario_id": "test_tx_22",
            "username": "new_persona_02",
            "profile": "good",
            "tx_type": "ACH",
            "amount": 112.00,
            "loc": _LOCATIONS[2],
            "country": "US",
            "merch": _GOOD_MERCHANTS[5],
            "card_present": False,
            "desc": "Completely new persona 'new_persona_02' domestic utility ACH payment ($112.00).",
        },
        {
            "scenario_id": "test_tx_23",
            "username": "new_persona_03",
            "profile": "bad",
            "tx_type": "CARD",
            "amount": 1650.00,
            "loc": _LOCATIONS[1],
            "country": "US",
            "merch": {"merchant_id": "merch_electronics_88", "name": "MegaTech Electronics", "mcc": "5732"},
            "card_present": False,
            "desc": "Completely new persona 'new_persona_03' high-value online electronics CARD purchase ($1,650.00).",
        },
        {
            "scenario_id": "test_tx_24",
            "username": "new_persona_04",
            "profile": "bad",
            "tx_type": "CARD",
            "amount": 3900.00,
            "loc": _ANOMALY_LOCATIONS[0],
            "country": "JP",
            "merch": _BAD_MERCHANTS[0],
            "card_present": False,
            "desc": "Completely new persona 'new_persona_04' high-risk overseas casino CARD purchase ($3,900.00).",
        },
        {
            "scenario_id": "test_tx_25",
            "username": "new_persona_05",
            "profile": "bad",
            "tx_type": "ACH",
            "amount": 5200.00,
            "loc": _ANOMALY_LOCATIONS[1],
            "country": "GB",
            "merch": _BAD_MERCHANTS[1],
            "card_present": False,
            "desc": "Completely new persona 'new_persona_05' high-risk overseas crypto ACH transfer ($5,200.00).",
        },
    ]

    for offset, spec in enumerate(new_persona_specs, start=21):
        is_ach = spec["tx_type"] == "ACH"
        loc = spec["loc"]
        merch = spec["merch"]
        tx_dt = ref_dt + timedelta(hours=offset - 18, minutes=rng.randint(1, 45))
        tx_details = {
            "transaction_id": f"tx_test_{offset:03d}",
            "transaction_type": spec["tx_type"],
            "amount": spec["amount"],
            "currency": "USD",
            "merchant": {
                "merchant_id": merch["merchant_id"],
                "name": merch["name"],
                "mcc": merch["mcc"],
                "country": spec["country"],
            },
        }
        if is_ach:
            tx_details["ach_details"] = {
                "routing_number": "021000021",
                "account_last_four": f"88{offset:02d}",
                "account_type": "CHECKING",
                "sec_code": "WEB",
                "direction": "DEBIT",
                "bank_name": "First National Bank",
            }
        else:
            tx_details["card_details"] = {
                "card_type": "CREDIT",
                "card_network": "VISA",
                "card_last_four": f"77{offset:02d}",
                "is_card_present": bool(spec["card_present"]),
                "expiration_month": 9,
                "expiration_year": 2028,
                "cvv_verified": True,
                "avs_result": "Y",
            }

        test_transactions.append(
            {
                "scenario_id": spec["scenario_id"],
                "persona_group": "new_persona",
                "transaction_profile": spec["profile"],
                "description": spec["desc"],
                "username": spec["username"],
                "datetime": tx_dt.isoformat(),
                "ip": f"192.0.2.{offset}",
                "device_id": f"dev_{spec['username']}",
                "location": {
                    "latitude": loc["lat"],
                    "longitude": loc["lon"],
                    "city": loc["city"],
                    "state": loc["state"],
                    "country": spec["country"],
                    "postal_code": loc["postal_code"],
                },
                "transaction_details": tx_details,
            }
        )

    return test_transactions


def write_test_transactions_dataset(
    dataset_dir: str | Path = DEFAULT_DATASET_DIR,
    seed: int = 42,
    reference_time: datetime | None = None,
) -> Path:
    """Write the 25 test transactions dataset to docs/dataset/test_transactions_dataset.json."""
    target_dir = Path(dataset_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    test_txs = generate_test_transactions_dataset(seed=seed, reference_time=reference_time)
    out_path = target_dir / "test_transactions_dataset.json"
    out_path.write_text(json.dumps(test_txs, indent=2), encoding="utf-8")
    return out_path


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
    test_tx_path = write_test_transactions_dataset(
        dataset_dir=target_dir,
        seed=seed,
        reference_time=reference_time,
    )

    return {
        "dataset_dir": str(target_dir),
        "user_profiles_file": str(up_path),
        "transactions_file": str(tx_path),
        "transaction_scores_file": str(scores_path),
        "test_transactions_file": str(test_tx_path),
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
    elif not (target_dir / "test_transactions_dataset.json").exists():
        write_test_transactions_dataset(dataset_dir=target_dir, seed=seed, reference_time=reference_time)

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
