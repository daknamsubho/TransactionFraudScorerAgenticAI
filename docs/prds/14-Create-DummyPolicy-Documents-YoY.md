# PRD-014: Create Policy Documents for Transactions Year on Year

## Status
- **Status**: Approved 


---
## 1. Executive Summary & Objective
I need to create some test policy documents which can be used to alter the scoring criteria and fraudulent behaviours. This will be used in the RAG so that I can show for a single Transactions how 2 different policies can alter the result. 

## 2. Requirements
I need
- Create 2 policy documents for Year 2025 and 2026
- Use Websearch to produce these dummy documents
- Store in `docs/policy-docs`



Details of the API can be found at `docs/openapi-spec/openapi.yaml`.
Model for the MCP can be found at `src/fraud_scorer/models/transaction.py`
DB Schema can be found here `docs/rdbms-model-schema/schema.sql`

## 3. Out-of-scope
- Webclient changes
- Notebook changes
- Code changes

