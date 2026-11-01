# Seed Datasets (`docs/dataset`)

## Overview
This directory contains the deterministic seed datasets for the SQLite RDBMS (`src/sqllite/fraud_scorer.db`), aligned with [schema.sql](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/docs/rdbms-model-schema/schema.sql):

- `user_profiles.json`: **40 user profiles**:
  - **30 Good Personas** (`good_persona_01` .. `good_persona_30`) created within the last **1 year** (`215`–`360` days before the reference timestamp).
  - **10 Bad Personas** (`bad_persona_01` .. `bad_persona_10`) created within the last **5 months** (`15`–`150` days before the reference timestamp).
- `transactions.json`: Historical `CARD` and `ACH` transactions:
  - **20 Good Personas** (`good_persona_01` .. `good_persona_20`) have **10–30 good transactions each week for the last 7 months** (`30` weeks).
  - **5 Bad Personas** (`bad_persona_01` .. `bad_persona_05`) have **2–5 good transactions in the last 2 weeks** (`14` days).
- `transaction_scores.json`: 1:1 corresponding score & disposition records (`status = 'APPROVE'`, low composite risk scores) mapped to `transactions(transaction_id)`.

## Generating Datasets & Seeding SQLite

Run the seeder script from the project root:

```bash
uv run python src/sqllite/seed.py --regenerate
```

Or invoke `seed_database()` from Python / Google Colab:

```python
from sqllite import seed_database

summary = seed_database()
print(summary)
```
