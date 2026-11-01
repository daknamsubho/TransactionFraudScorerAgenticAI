# PRD-012: Load datasets in Webclient for Manual Testing

## Status
- **Status**: Approved 


---
## 1. Executive Summary & Objective
I need to update the Webclient Transaction form page `index.html` so that I can prefill the form with Test Transactions for manual testing.

## 2. Requirements
I need
- Update to the index.html with 3 new buttons. 
- First Button - Import Random transaction from test_transaction_dataset - This is import a random Transaction from the predetermined test dataset.
- Second Button - Generate Good Transaction - It should generate a complete new good transaction
- Third Button - Generate Fraud Transaction - It should generate a complete new bad transaction
- Add a section that display the details of the Test.

Do the following
- Update the `notebooks/colab_setup_and_run.ipynb` to add the steps that is required for the executing


Details of the API can be found at `docs/openapi-spec/openapi.yaml`.
Model for the MCP can be found at `src/fraud_scorer/models/transaction.py`
DB Schema can be found here `docs/rdbms-model-schema/schema.sql`

## 3. Out-of-scope
- APIGateway

