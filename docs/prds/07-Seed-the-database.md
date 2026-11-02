# PRD-003: Seed the database

## Status
- **Status**: Approved 


---
## 1. Executive Summary & Objective
I need to seed the database with mock data

## 2. Requirements
I need
- 30 good personas created in last 1 year
- 10 bad personas created in last 5 months
- 20 good personas to have 10-30 good transactions each week for last 7 months. 
- 5 bad personas to have 2-5 good transactions in last 2 weeks
- Create seed data based on the schemas that I can insert into the database
- Create the datasets at `docs/dataset`


Do the following
- Update the `notebooks/colab_setup_and_run.ipynb` to add the steps that is required for the executing


Details of the API can be found at `docs/openapi-spec/openapi.yaml`.
Model for the MCP can be found at `src/fraud_scorer/models/transaction.py`

## 3. Out-of-scope

