# PRD-019: LLM Model changes

## Status
- **Status**: Approved 


---
## 1. Executive Summary & Objective
Based on `docs/plans/17-Update-Agents.md` we created multiple Tiers of LLM. Tier 3 is qwen3.8:27B model. This is causing some latency in the performance. Keep the Tier system and replace the qwen3.8:27B with llama3.1:8b. This will prove the configurality of the system.

## 2. Requirements
I need
- replace qwen3.8:27B with llama3.1:8b


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



