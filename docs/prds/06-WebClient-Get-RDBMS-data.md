# PRD-006: Webclient to view the RDBMS data 

## Status
- **Status**: Approved 


---
## 1. Executive Summary & Objective
I need the Webclient to display the RDBMS data 

## 2. Requirements
I need
- Update the Openapi spec to create GET, PUT, POST, DELETE the Database tables
- Update the API Gateway to implement the updated OpenAPI spec
- Update the Webclient to view the data from the tables
- Each table should have its own page in Webclient
- In Webclient tables should be paginated for view


Do the following
- Update the `notebooks/colab_setup_and_run.ipynb` to add the steps that is required for the executing


Details of the API can be found at `docs/openapi-spec/openapi.yaml`.
Model for the MCP can be found at `src/fraud_scorer/models/transaction.py`
DB Schema can be found here `docs/rdbms-model-schema/schema.sql`

## 3. Out-of-scope

