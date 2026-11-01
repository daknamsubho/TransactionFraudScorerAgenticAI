"""Parameterized SQL queries (SELECT, INSERT, UPDATE, DELETE) for the SQLite RDBMS."""

# =============================================================================
# 1. UserProfile Queries (user_profiles)
# =============================================================================

INSERT_USER_PROFILE_SQL = """
INSERT INTO user_profiles (
    username,
    created_date,
    address,
    city,
    state,
    country,
    postal_code,
    updated_at
) VALUES (
    :username,
    :created_date,
    :address,
    :city,
    :state,
    :country,
    :postal_code,
    :updated_at
);
"""

UPSERT_USER_PROFILE_SQL = """
INSERT INTO user_profiles (
    username,
    created_date,
    address,
    city,
    state,
    country,
    postal_code,
    updated_at
) VALUES (
    :username,
    :created_date,
    :address,
    :city,
    :state,
    :country,
    :postal_code,
    :updated_at
)
ON CONFLICT(username) DO UPDATE SET
    address = COALESCE(excluded.address, user_profiles.address),
    city = COALESCE(excluded.city, user_profiles.city),
    state = COALESCE(excluded.state, user_profiles.state),
    country = COALESCE(excluded.country, user_profiles.country),
    postal_code = COALESCE(excluded.postal_code, user_profiles.postal_code),
    updated_at = excluded.updated_at;
"""

SELECT_USER_PROFILE_BY_USERNAME_SQL = """
SELECT
    username,
    created_date,
    address,
    city,
    state,
    country,
    postal_code,
    updated_at
FROM user_profiles
WHERE username = :username;
"""

SELECT_ALL_USER_PROFILES_SQL = """
SELECT
    username,
    created_date,
    address,
    city,
    state,
    country,
    postal_code,
    updated_at
FROM user_profiles
ORDER BY created_date DESC;
"""

COUNT_USER_PROFILES_SQL = """
SELECT COUNT(*) AS total FROM user_profiles;
"""

SELECT_USER_PROFILES_PAGINATED_SQL = """
SELECT
    username,
    created_date,
    address,
    city,
    state,
    country,
    postal_code,
    updated_at
FROM user_profiles
ORDER BY created_date DESC, username ASC
LIMIT :limit OFFSET :offset;
"""

UPDATE_USER_PROFILE_SQL = """
UPDATE user_profiles
SET
    address = :address,
    city = :city,
    state = :state,
    country = :country,
    postal_code = :postal_code,
    updated_at = :updated_at
WHERE username = :username;
"""

DELETE_USER_PROFILE_SQL = """
DELETE FROM user_profiles
WHERE username = :username;
"""

# =============================================================================
# 2. Transaction Queries (transactions)
# =============================================================================

INSERT_TRANSACTION_SQL = """
INSERT INTO transactions (
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

SELECT_TRANSACTION_BY_ID_SQL = """
SELECT
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
FROM transactions
WHERE transaction_id = :transaction_id;
"""

SELECT_TRANSACTIONS_BY_USERNAME_SQL = """
SELECT
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
FROM transactions
WHERE username = :username
ORDER BY timestamp DESC;
"""

SELECT_TRANSACTIONS_BY_STATUS_SQL = """
SELECT
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
FROM transactions
WHERE status = :status
ORDER BY timestamp DESC;
"""

UPDATE_TRANSACTION_STATUS_SQL = """
UPDATE transactions
SET
    status = :status,
    updated_at = :updated_at
WHERE transaction_id = :transaction_id;
"""

UPDATE_TRANSACTION_RECORD_SQL = """
UPDATE transactions
SET
    amount = COALESCE(:amount, amount),
    city = COALESCE(:city, city),
    state = COALESCE(:state, state),
    country = COALESCE(:country, country),
    merchant_name = COALESCE(:merchant_name, merchant_name),
    mcc = COALESCE(:mcc, mcc),
    status = COALESCE(:status, status),
    updated_at = :updated_at
WHERE transaction_id = :transaction_id;
"""

COUNT_TRANSACTIONS_SQL = """
SELECT COUNT(*) AS total
FROM transactions
WHERE (:username IS NULL OR username = :username)
  AND (:status IS NULL OR status = :status);
"""

SELECT_TRANSACTIONS_PAGINATED_SQL = """
SELECT
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
FROM transactions
WHERE (:username IS NULL OR username = :username)
  AND (:status IS NULL OR status = :status)
ORDER BY timestamp DESC, transaction_id DESC
LIMIT :limit OFFSET :offset;
"""

DELETE_TRANSACTION_SQL = """
DELETE FROM transactions
WHERE transaction_id = :transaction_id;
"""

# =============================================================================
# 3. Transaction Scores & Dispositions Queries (transaction_scores)
# =============================================================================

INSERT_TRANSACTION_SCORE_SQL = """
INSERT INTO transaction_scores (
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

SELECT_TRANSACTION_SCORE_BY_TX_ID_SQL = """
SELECT
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
FROM transaction_scores
WHERE transaction_id = :transaction_id;
"""

SELECT_TRANSACTION_WITH_SCORE_BY_TX_ID_SQL = """
SELECT
    t.transaction_id,
    t.username,
    t.transaction_type,
    t.amount,
    t.currency,
    t.timestamp,
    t.ip_address,
    t.device_id,
    t.latitude,
    t.longitude,
    t.city,
    t.state,
    t.country,
    t.postal_code,
    t.merchant_id,
    t.merchant_name,
    t.mcc,
    t.merchant_country,
    t.payment_method_type,
    t.card_or_account_last_four,
    t.is_card_present,
    t.payment_details_json,
    t.status,
    t.created_at,
    t.updated_at,
    s.assessment_id,
    s.score,
    s.approval_status,
    s.decision_accepted,
    s.decision_reason,
    s.reasoning_summary,
    s.risk_factors_json,
    s.tools_invoked_json,
    s.evaluated_at,
    s.decided_at
FROM transactions t
LEFT JOIN transaction_scores s
    ON t.transaction_id = s.transaction_id
WHERE t.transaction_id = :transaction_id;
"""

UPDATE_TRANSACTION_SCORE_SQL = """
UPDATE transaction_scores
SET
    score = :score,
    approval_status = :approval_status,
    decision_accepted = :decision_accepted,
    decision_reason = :decision_reason,
    reasoning_summary = :reasoning_summary,
    risk_factors_json = :risk_factors_json,
    tools_invoked_json = :tools_invoked_json,
    decided_at = :decided_at
WHERE transaction_id = :transaction_id;
"""

UPDATE_TRANSACTION_DECISION_SQL = """
UPDATE transaction_scores
SET
    approval_status = :approval_status,
    decision_accepted = :decision_accepted,
    decision_reason = :decision_reason,
    decided_at = :decided_at
WHERE transaction_id = :transaction_id;
"""

DELETE_TRANSACTION_SCORE_SQL = """
DELETE FROM transaction_scores
WHERE transaction_id = :transaction_id;
"""

COUNT_TRANSACTION_SCORES_SQL = """
SELECT COUNT(*) AS total FROM transaction_scores;
"""

SELECT_TRANSACTION_SCORES_PAGINATED_SQL = """
SELECT
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
FROM transaction_scores
ORDER BY evaluated_at DESC, transaction_id DESC
LIMIT :limit OFFSET :offset;
"""

# =============================================================================
# 4. Aggregation Query for Dynamic Tool Calculations
# =============================================================================

SELECT_USER_TRANSACTION_STATS_SQL = """
SELECT
    COUNT(t.transaction_id) AS total_transactions,
    COALESCE(AVG(t.amount), 100.0) AS avg_transaction_amount,
    SUM(
        CASE
            WHEN t.status IN ('DECLINE', 'REJECTED')
              OR s.approval_status IN ('DECLINE', 'REJECTED')
              OR s.decision_accepted = 0
            THEN 1
            ELSE 0
        END
    ) AS prior_disputes
FROM transactions t
LEFT JOIN transaction_scores s
    ON t.transaction_id = s.transaction_id
WHERE t.username = :username;
"""
