# Seed & UI Test Datasets (`docs/dataset`)

## Overview
This directory contains the deterministic seed datasets and UI/API test datasets for the SQLite RDBMS (`src/sqllite/fraud_scorer.db`), aligned with [schema.sql](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/docs/rdbms-model-schema/schema.sql) and [openapi.yaml](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/docs/openapi-spec/openapi.yaml):

- `user_profiles.json`: **40 user profiles**:
  - **30 Good Personas** (`good_persona_01` .. `good_persona_30`) created within the last **1 year** (`215`–`360` days before the reference timestamp).
  - **10 Bad Personas** (`bad_persona_01` .. `bad_persona_10`) created within the last **5 months** (`15`–`150` days before the reference timestamp).
- `transactions.json`: Historical `CARD` and `ACH` transactions:
  - **20 Good Personas** (`good_persona_01` .. `good_persona_20`) have **10–30 good transactions each week for the last 7 months** (`30` weeks).
  - **5 Bad Personas** (`bad_persona_01` .. `bad_persona_05`) have **2–5 good transactions in the last 2 weeks** (`14` days).
- `transaction_scores.json`: 1:1 corresponding score & disposition records (`status = 'APPROVE'`, low composite risk scores) mapped to `transactions(transaction_id)`.
- `test_transactions_dataset.json`: **25 UI & API test transactions** (`TransactionIngestRequest` payloads for `POST /api/v1/transactions/score`):
  - **20 Transactions from Existing Personas (`test_tx_01` .. `test_tx_20`)**:
    - `test_tx_01` .. `test_tx_10`: **10 Good Transactions** (`good_persona_01` .. `good_persona_10`) in their home cities at low-risk merchants (`5411`, `5814`, `5541`, `5912`, `5311`, `4900`, `5812`, `5942`) across `CARD` and `ACH` rails.
    - `test_tx_11` .. `test_tx_20`: **10 Bad Transactions** (`bad_persona_01` .. `bad_persona_05`, `good_persona_11` .. `good_persona_15`) exhibiting impossible travel (Tokyo, London, Lagos, Frankfurt, Sydney 12 minutes after domestic activity), high-risk MCCs (`7995`, `6051`, `4829`, `5967`, `5933`), and large spend spikes (`$2,825.00` – `$6,200.00`).
  - **5 Transactions from Completely New Personas (`test_tx_21` .. `test_tx_25`)**:
    - `new_persona_01` .. `new_persona_05` (not present in `user_profiles.json`), covering both low-risk domestic onboarding purchases and high-risk overseas/high-value transactions.

## Generating Datasets & Seeding SQLite

Run the seeder script from the project root:

```bash
uv run python src/sqllite/seed.py --regenerate
```

Or invoke `seed_database()` and `generate_test_transactions_dataset()` from Python / Google Colab:

```python
from sqllite import generate_test_transactions_dataset, seed_database

summary = seed_database()
test_txs = generate_test_transactions_dataset()
print(summary, len(test_txs))
```
