"""SQLite database connection and schema initialization for Transaction Fraud Scorer."""

import sqlite3
from pathlib import Path

SQLLITE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SQLLITE_DIR.parent.parent
SCHEMA_SQL_PATH = PROJECT_ROOT / "docs" / "rdbms-model-schema" / "schema.sql"
DEFAULT_DB_PATH = SQLLITE_DIR / "fraud_scorer.db"

_FALLBACK_SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS user_profiles (
    username TEXT PRIMARY KEY,
    created_date TEXT NOT NULL,
    address TEXT,
    city TEXT,
    state TEXT,
    country TEXT NOT NULL DEFAULT 'US',
    postal_code TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS transactions (
    transaction_id TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    transaction_type TEXT NOT NULL CHECK (transaction_type IN ('CARD', 'ACH')),
    amount REAL NOT NULL CHECK (amount > 0),
    currency TEXT NOT NULL DEFAULT 'USD',
    timestamp TEXT NOT NULL,
    ip_address TEXT,
    device_id TEXT,
    latitude REAL NOT NULL CHECK (latitude >= -90.0 AND latitude <= 90.0),
    longitude REAL NOT NULL CHECK (longitude >= -180.0 AND longitude <= 180.0),
    city TEXT,
    state TEXT,
    country TEXT NOT NULL DEFAULT 'US',
    postal_code TEXT,
    merchant_id TEXT,
    merchant_name TEXT,
    mcc TEXT,
    merchant_country TEXT DEFAULT 'US',
    payment_method_type TEXT,
    card_or_account_last_four TEXT,
    is_card_present INTEGER NOT NULL DEFAULT 0 CHECK (is_card_present IN (0, 1)),
    payment_details_json TEXT,
    status TEXT NOT NULL DEFAULT 'REVIEW' CHECK (
        status IN ('PENDING', 'APPROVE', 'REVIEW', 'DECLINE', 'ACCEPTED', 'REJECTED')
    ),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (username) REFERENCES user_profiles(username) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_transactions_username_ts
    ON transactions(username, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_transactions_status
    ON transactions(status);

CREATE TABLE IF NOT EXISTS transaction_scores (
    assessment_id TEXT PRIMARY KEY,
    transaction_id TEXT NOT NULL UNIQUE,
    score REAL NOT NULL CHECK (score >= 0.0 AND score <= 100.0),
    approval_status TEXT NOT NULL CHECK (
        approval_status IN ('APPROVE', 'REVIEW', 'DECLINE', 'ACCEPTED', 'REJECTED')
    ),
    decision_accepted INTEGER CHECK (decision_accepted IN (0, 1) OR decision_accepted IS NULL),
    decision_reason TEXT,
    reasoning_summary TEXT NOT NULL,
    risk_factors_json TEXT NOT NULL DEFAULT '[]',
    tools_invoked_json TEXT NOT NULL DEFAULT '[]',
    langsmith_run_id TEXT,
    evaluated_at TEXT NOT NULL,
    decided_at TEXT,
    FOREIGN KEY (transaction_id) REFERENCES transactions(transaction_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_transaction_scores_tx_id
    ON transaction_scores(transaction_id);
"""


def get_schema_sql() -> str:
    """Load the DDL schema from docs/rdbms-model-schema/schema.sql."""
    if SCHEMA_SQL_PATH.exists():
        return SCHEMA_SQL_PATH.read_text(encoding="utf-8")
    return _FALLBACK_SCHEMA_SQL


def get_connection(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Create a SQLite connection with row factory and foreign keys enabled."""
    target = Path(db_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path: str | Path = DEFAULT_DB_PATH) -> Path:
    """Initialize the SQLite database tables and indexes from docs/rdbms-model-schema/schema.sql."""
    target = Path(db_path)
    schema_sql = get_schema_sql()
    with get_connection(target) as conn:
        conn.executescript(schema_sql)
        # Idempotent migration for existing databases created prior to PRD-018
        cols = [
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(transaction_scores);").fetchall()
        ]
        if "langsmith_run_id" not in cols:
            conn.execute("ALTER TABLE transaction_scores ADD COLUMN langsmith_run_id TEXT;")
        conn.commit()
    return target
