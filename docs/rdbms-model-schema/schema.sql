-- =============================================================================
-- SQLite Relational Schema for Transaction Fraud Scorer Agentic AI
-- Location: docs/rdbms-model-schema/schema.sql
-- =============================================================================

PRAGMA foreign_keys = ON;

-- -----------------------------------------------------------------------------
-- 1. UserProfile Table (user_profiles)
-- Stores customer profile identity, registration timestamp, and address.
-- Note: trust_tier, prior_disputes, and avg_transaction_amount are NOT stored
-- here; they are dynamically calculated in the MCP tool from historical records.
-- -----------------------------------------------------------------------------
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

-- -----------------------------------------------------------------------------
-- 2. Transaction Table (transactions)
-- Stores historical and ongoing financial transactions (CARD and ACH) along
-- with current transaction status.
-- -----------------------------------------------------------------------------
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

-- -----------------------------------------------------------------------------
-- 3. Transaction Scores & Dispositions Table (transaction_scores)
-- Stores fraud scores, approval status, risk factor details, and manual
-- analyst Accept/Reject decisions mapped 1:1 to transactions(transaction_id).
-- -----------------------------------------------------------------------------
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
    evaluated_at TEXT NOT NULL,
    decided_at TEXT,
    FOREIGN KEY (transaction_id) REFERENCES transactions(transaction_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_transaction_scores_tx_id
    ON transaction_scores(transaction_id);
