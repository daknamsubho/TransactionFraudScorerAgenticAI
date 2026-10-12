"""Risk evaluation tools exposed via Model Context Protocol (MCP)."""

import math
from datetime import UTC, datetime
from typing import Any

# High-risk Merchant Category Codes (MCC)
HIGH_RISK_MCCS: dict[str, str] = {
    "7995": "Betting, Casino Gaming & Gambling",
    "6051": "Quasi Cash - Cryptocurrency & Foreign Currency",
    "4829": "Wire Transfer & Money Orders",
    "5967": "Direct Marketing - Outbound Telemarketing",
    "5993": "Cigar Stores & Stands",
}

# In-memory mock account history store for demonstration and testing
_MOCK_ACCOUNT_DATA: dict[str, dict[str, Any]] = {
    "acc_suspicious_01": {
        "account_age_days": 4,
        "chargeback_count": 2,
        "avg_spend": 25.0,
        "trust_tier": "untrusted",
        "last_location": {"latitude": 51.5074, "longitude": -0.1278, "city": "London"},  # London
        "last_timestamp": "2026-10-12T11:00:00Z",
        "recent_tx_count_1h": 8,
        "recent_tx_volume_1h": 3200.0,
    },
    "acc_normal_01": {
        "account_age_days": 820,
        "chargeback_count": 0,
        "avg_spend": 110.0,
        "trust_tier": "established",
        "last_location": {"latitude": 37.7749, "longitude": -122.4194, "city": "San Francisco"},
        "last_timestamp": "2026-10-12T08:00:00Z",
        "recent_tx_count_1h": 1,
        "recent_tx_volume_1h": 45.0,
    },
}


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great-circle distance between two points on the Earth (in km)."""
    r = 6371.0  # Earth's radius in kilometers
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return round(r * c, 2)


def check_velocity(account_id: str, window_minutes: int = 60) -> dict[str, Any]:
    """Analyze transaction frequency and total volume in a recent time window.

    Args:
        account_id: Customer account identifier.
        window_minutes: Time window in minutes to evaluate (default 60).

    Returns:
        Dictionary containing transaction count, volume, velocity score (0-100),
        and burst status.
    """
    account_info = _MOCK_ACCOUNT_DATA.get(account_id, {})
    tx_count = account_info.get("recent_tx_count_1h", 1)
    tx_volume = account_info.get("recent_tx_volume_1h", 50.0)

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
        "transaction_count": tx_count,
        "cumulative_volume": tx_volume,
        "is_burst": is_burst,
        "velocity_risk_score": score,
        "reasoning": reason,
    }


def check_geo_anomaly(
    account_id: str,
    current_lat: float,
    current_lon: float,
    current_timestamp_iso: str | None = None,
) -> dict[str, Any]:
    """Check for impossible travel speed and distant consecutive transactions.

    Args:
        account_id: Customer account identifier.
        current_lat: Current transaction latitude.
        current_lon: Current transaction longitude.
        current_timestamp_iso: Current transaction timestamp in ISO-8601 format.

    Returns:
        Dictionary with distance (km), elapsed time, implied speed (km/h), and geo risk score.
    """
    account_info = _MOCK_ACCOUNT_DATA.get(account_id, {})
    last_loc = account_info.get(
        "last_location",
        {"latitude": current_lat, "longitude": current_lon, "city": "Unknown"},
    )
    last_lat = last_loc["latitude"]
    last_lon = last_loc["longitude"]

    dist_km = haversine_distance(last_lat, last_lon, current_lat, current_lon)

    # Calculate time delta
    last_time_str = account_info.get("last_timestamp", "2026-10-12T11:00:00Z")
    try:
        t_last = datetime.fromisoformat(last_time_str.replace("Z", "+00:00"))
        t_curr = (
            datetime.fromisoformat(current_timestamp_iso.replace("Z", "+00:00"))
            if current_timestamp_iso
            else datetime.now(UTC)
        )
        elapsed_hours = max((t_curr - t_last).total_seconds() / 3600.0, 0.05)
    except Exception:
        elapsed_hours = 1.0

    speed_kmh = round(dist_km / elapsed_hours, 1)
    impossible_travel = speed_kmh > 850.0 and dist_km > 500.0

    if impossible_travel:
        score = 95.0
        reason = (
            f"Impossible travel detected: {dist_km:.1f} km traversed in {elapsed_hours:.2f}h "
            f"({speed_kmh:.1f} km/h, exceeds commercial flight speeds)."
        )
    elif dist_km > 2000.0:
        score = 45.0
        reason = f"Cross-regional transaction: {dist_km:.1f} km from last known activity."
    else:
        score = 5.0
        reason = f"Normal geographic proximity: {dist_km:.1f} km from prior location."

    return {
        "account_id": account_id,
        "distance_km": dist_km,
        "elapsed_hours": round(elapsed_hours, 2),
        "speed_kmh": speed_kmh,
        "impossible_travel": impossible_travel,
        "geo_risk_score": score,
        "reasoning": reason,
    }


def check_merchant_risk(merchant_id: str, mcc: str) -> dict[str, Any]:
    """Evaluate risk associated with the merchant and its Merchant Category Code (MCC).

    Args:
        merchant_id: Unique merchant identifier.
        mcc: 4-digit Merchant Category Code.

    Returns:
        Dictionary with MCC risk analysis, category name, and risk score.
    """
    category_name = HIGH_RISK_MCCS.get(mcc, "Standard Commercial Category")
    is_high_risk = mcc in HIGH_RISK_MCCS

    if is_high_risk:
        score = 70.0
        reason = f"High-risk MCC {mcc} ({category_name}) with elevated chargeback propensity."
    else:
        score = 10.0
        reason = f"Standard merchant category MCC {mcc} ({category_name})."

    return {
        "merchant_id": merchant_id,
        "mcc": mcc,
        "category_name": category_name,
        "is_high_risk_mcc": is_high_risk,
        "merchant_risk_score": score,
        "reasoning": reason,
    }


def lookup_account_history(account_id: str) -> dict[str, Any]:
    """Retrieve historical account age, chargeback history, and reputation.

    Args:
        account_id: Customer account identifier.

    Returns:
        Dictionary with account age, chargeback history, trust tier, and risk score.
    """
    account_info = _MOCK_ACCOUNT_DATA.get(account_id, {})
    age_days = account_info.get("account_age_days", 180)
    chargebacks = account_info.get("chargeback_count", 0)
    trust_tier = account_info.get("trust_tier", "standard")

    if chargebacks >= 2 or (age_days < 7 and trust_tier == "untrusted"):
        score = 85.0
        reason = f"High risk account: new account ({age_days} days old) with {chargebacks} prior dispute(s)."
    elif age_days < 14:
        score = 40.0
        reason = f"New account profile: {age_days} days since registration."
    else:
        score = 5.0
        reason = f"Established account: {age_days} days active, {chargebacks} prior dispute(s)."

    return {
        "account_id": account_id,
        "account_age_days": age_days,
        "chargeback_count": chargebacks,
        "trust_tier": trust_tier,
        "account_risk_score": score,
        "reasoning": reason,
    }
