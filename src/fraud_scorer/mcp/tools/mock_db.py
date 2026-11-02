"""MockDB data and feature provider backing the MCP fraud risk tools."""

from typing import Any

# High-risk Merchant Category Codes (MCC)
HIGH_RISK_MCCS: dict[str, str] = {
    "7995": "Betting, Casino Gaming & Gambling",
    "6051": "Quasi Cash - Cryptocurrency & Foreign Currency",
    "4829": "Wire Transfer & Money Orders",
    "5967": "Direct Marketing - Outbound Telemarketing",
    "5993": "Cigar Stores & Stands",
}

# In-memory mock account history store (MockDB) for demonstration and testing
MOCK_ACCOUNT_DATA: dict[str, dict[str, Any]] = {
    "acc_suspicious_01": {
        "account_age_days": 4,
        "chargeback_count": 2,
        "avg_spend": 25.0,
        "trust_tier": "untrusted",
        "last_location": {"latitude": 51.5074, "longitude": -0.1278, "city": "London"},
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


def get_account_profile(account_id: str) -> dict[str, Any]:
    """Retrieve account features from MockDB."""
    return MOCK_ACCOUNT_DATA.get(account_id, {})
