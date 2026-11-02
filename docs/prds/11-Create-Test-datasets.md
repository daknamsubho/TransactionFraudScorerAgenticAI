# PRD-011: Create Test datasets

## Status
- **Status**: Approved 


---
## 1. Executive Summary & Objective
I need to create some test data sets for testing through UI 

## 2. Requirements
I need
- Create 20 Transaction with mix of good and bad from exisiting personas
- Create 5 Transactions with completely new personas. No need to create these personas in DB.
- Store in `docs/dataset`
- Name the file as test_transactions_dataset

Do the following
- Update the `notebooks/colab_setup_and_run.ipynb` to add the steps that is required for the executing


Details of the API can be found at `docs/openapi-spec/openapi.yaml`.
Model for the MCP can be found at `src/fraud_scorer/models/transaction.py`
DB Schema can be found here `docs/rdbms-model-schema/schema.sql`

## 3. Out-of-scope
- Webclient changes

