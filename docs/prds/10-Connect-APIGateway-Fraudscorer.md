# PRD-010: Connect APi Gateway with Fraud Scorer

## Status
- **Status**: Approved 


---
## 1. Executive Summary & Objective
I need to now connect the API gateway to the Fraudscorer so that the FraudScorer can ingest the Transaction Request recieved via APIGateway, score the Transaction and return the result back to Webclient via APIgateway for Feedback. 

## 2. Requirements
I need
- Connect the Fraud Scorer Injestion from API Gateway
- The Orchestrator agent should recieve the Request and process it


Do the following
- Update the `notebooks/colab_setup_and_run.ipynb` to add the steps that is required for the executing


Details of the API can be found at `docs/openapi-spec/openapi.yaml`.
Model for the MCP can be found at `src/fraud_scorer/models/transaction.py`
DB Schema can be found here `docs/rdbms-model-schema/schema.sql`

## 3. Out-of-scope
- Communication Service
- Observability Agent
- Governance Agent
- RAG Layer

