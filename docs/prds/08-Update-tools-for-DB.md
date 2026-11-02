# PRD-003: Update Tools for DB

## Status
- **Status**: Approved 


---
## 1. Executive Summary & Objective
I need to update the tools to connect to DB so that it can get actual historical data for users and their transactions

## 2. Requirements
I need
- Update the MCP tool to connect to the Database schemas to get historical values for calculation


Do the following
- Update the `notebooks/colab_setup_and_run.ipynb` to add the steps that is required for the executing


Details of the API can be found at `docs/openapi-spec/openapi.yaml`.
Model for the MCP can be found at `src/fraud_scorer/models/transaction.py`
DB Schema can be found here `docs/rdbms-model-schema/schema.sql`

## 3. Out-of-scope

