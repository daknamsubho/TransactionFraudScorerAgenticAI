# PRD-009: Create Agents and Skills

## Status
- **Status**: Approved 


---
## 1. Executive Summary & Objective
I need to create Agents with specific skills to call the tools and take decision based on the architecture diagram in the Fraud scorer system. The Orchestrator is just a manager agent. The Orchestrator agent does not take any decison. It provides all relevant data to the Decision agent that pass back to the API Gateway to send the score and decsion back to the Webclient. The system uses Langchain. The Communication Service will be developed at later iteration.

## 2. Requirements
I need
- To Create individual agents based on the architecture
- Create Orchestrator, Analysis Agent, Data Retriever agent and Decision Agent.
- All Agents should be configured via flags that I can turn on and off
- Each Agents should be created in seperate files
- Each Skills should be created in seperate files 
- Orchestrator does not do any decisioning
- Need to be developed using Langchain


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

