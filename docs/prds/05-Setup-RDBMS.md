# PRD-003: Setup Persistnance RDBMS database for the Historical and ongoing Transaction records

## Status
- **Status**: Approved 


---
## 1. Executive Summary & Objective
I need to Create a lite RDBMS database which will store historical and ongoing Transactions. This will also store the User profile related data.
I will populate the data later.

## 2. Requirements
I need
- Create a RDBMS database
- Use SQLLite
- Create SELECT, INSERT, UPDATE, DELETE queries under `src\sqllite`
- Create schemas based on the models here `docs/rdbms-model-schema`
- Create Transaction table with Status
- Create Scores, Approval Status, etc that map to TransactionId in a seperate table
- Create UserProfile table that hase Username, createddate, address columns 
- In user profile no need to add `trust_tier`, `prior_disputes`, `avg_transaction_amount`. Those data need to be calculated in the tool
- The SQLLite installation should also be saved at `src\sqllite`. `colab_setup_and_run.ipynb` should read from it.


Do the following
- Update the `notebooks/colab_setup_and_run.ipynb` to add the steps that is required for the executing


Details of the API can be found at `docs/openapi-spec/openapi.yaml`.
Model for the MCP can be found at `src/fraud_scorer/models/transaction.py`

## 3. Out-of-scope

