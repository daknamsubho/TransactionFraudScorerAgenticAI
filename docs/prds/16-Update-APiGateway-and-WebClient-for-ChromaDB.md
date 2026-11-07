# PRD-015: Need UI to query and view data from ChromaDB Vector database

## Status
- **Status**: Approved 


---
## 1. Executive Summary & Objective
I want a page in the Webclient that can help to show query and response from ChromaDB

## 2. Requirements
I need
- Update APIGateway OpenAPI spec to integrate the ChromaDB APIs to query, view query response, Input for top K and upload new documents 
- Update APIGateway to implement the OpenAPI spec
- Update Webclient to Query, View Result, Filter for Top K and Upload new documents
- Use ChromaDB


Do the following
- Update the `notebooks/colab_setup_and_run.ipynb` to add the steps that is required for the executing


Details of the API can be found at `docs/openapi-spec/openapi.yaml`.
Model for the MCP can be found at `src/fraud_scorer/models/transaction.py`
DB Schema can be found here `docs/rdbms-model-schema/schema.sql`

## 3. Out-of-scope


