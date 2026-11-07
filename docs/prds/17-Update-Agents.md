# PRD-017: Update Agents based on the agentic-architecture pattern

## Status
- **Status**: Approved 


---
## 1. Executive Summary & Objective
I have created the Agentic Architecture pattern in `docs/agentic-architecture-pattern.md`. It shows how the agents would interact and communicate with each other. I would like to alter the current code to adhere to the new architecture. Let me know if you see any contradictions or performance issues. Provide me suggestions if any so that I can take decisions if that should be implemented.

## 2. Requirements
I need
- Use `docs/agentic-architecture-pattern.md` to alter the Agentic AI pattern
- Use Langgraph 
- Use ChromaDB
- Use SQLLite


Do the following
- Update the `notebooks/colab_setup_and_run.ipynb` to add the steps that is required for the executing


Details of the API can be found at `docs/openapi-spec/openapi.yaml`.
Model for the MCP can be found at `src/fraud_scorer/models/transaction.py`
DB Schema can be found here `docs/rdbms-model-schema/schema.sql`

## 3. Out-of-scope
- Webclient changes
- APIGateway changes
- SQLLite changes
- Chroma DB changes
- Observability Agent
- Governance Agent


