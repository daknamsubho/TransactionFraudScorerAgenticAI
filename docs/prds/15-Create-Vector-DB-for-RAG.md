# PRD-015: Create Vector Database for RAG

## Status
- **Status**: Approved 


---
## 1. Executive Summary & Objective
For RAG I want to use ChromaDB. Hence I need the create a setup process for that

## 2. Requirements
I need
- Create a Vector Database
- Use ChromaDB
- Store all installation related files in `src/chromadb`

Do the following
- Update the `notebooks/colab_setup_and_run.ipynb` to add the steps that is required for the executing


Details of the API can be found at `docs/openapi-spec/openapi.yaml`.
Model for the MCP can be found at `src/fraud_scorer/models/transaction.py`
DB Schema can be found here `docs/rdbms-model-schema/schema.sql`

## 3. Out-of-scope
- Webclient changes

