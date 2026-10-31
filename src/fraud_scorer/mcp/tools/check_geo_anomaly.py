"""MCP Tool: check_geo_anomaly — Detect impossible travel and geographic anomalies."""

import math
from datetime import UTC, datetime
from typing import Any

from fraud_scorer.mcp.tools.mock_db import get_account_profile


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great-circle distance between two points on the Earth (in km)."""
    r = 6371.0  # Earth's radius in kilometers
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return round(r * c, 2)


def check_geo_anomaly(
    account_id: str,
    current_lat: float,
    current_lon: float,
    current_timestamp_iso: str | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Check for impossible travel speed and distant consecutive transactions.

    Args:
        account_id: Customer account identifier.
        current_lat: Current transaction latitude (-90.0 to 90.0).
        current_lon: Current transaction longitude (-180.0 to 180.0).
        current_timestamp_iso: Current transaction timestamp in ISO-8601 format.
        timestamp: Optional alias for current_timestamp_iso per architecture contract.

    Returns:
        Dictionary with distance_km, elapsed_hours, speed_kmh, impossible_travel, and geo_risk_score.
    """
    account_info = get_account_profile(account_id)
    last_loc = account_info.get(
        "last_location",
        {"latitude": current_lat, "longitude": current_lon, "city": "Unknown"},
    )
    last_lat = float(last_loc["latitude"])
    last_lon = float(last_loc["longitude"])

    dist_km = haversine_distance(last_lat, last_lon, current_lat, current_lon)

    effective_ts = current_timestamp_iso or timestamp
    last_time_str = str(account_info.get("last_timestamp", "2026-10-12T11:00:00Z"))
    try:
        t_last = datetime.fromisoformat(last_time_str.replace("Z", "+00:00"))
        t_curr = (
            datetime.fromisoformat(effective_ts.replace("Z", "+00:00"))
            if effective_ts
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
