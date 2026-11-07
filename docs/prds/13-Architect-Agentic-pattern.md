# PRD-013: Architect Agentic pattern

## Status
- **Status**: Approved 


---
## 1. Executive Summary & Objective
As an architect I am thinking to use a hybrid pattern to design the agentic system
I am using bellow agents
- Orchestrator
- Data Retrieval Agents
- Analysis Agent
- Desicion Agent
- Ovservability Agent
- Govenrnance Agent

I am thinking to add another agent as Evaluator agent to evaluate the decision made.

Orchestrator should follow the Supervisor pattern and get data from Data Retrieval Agent first before Analysis Agent perform any task.
But Analysis agent can call Data Retrieval agent to gather more information. Once Analysis is done, Decision agent should be called and then Evaluator agent. Evaluator agent can createa feedback loop to the Orchestrator if necessary. The maximan retry it can do is 3.
Obervability and Governance Agents should not be under Orchestrator. Observaliity and Governance should omnipresent to interact with other agents and acts as Gaurdrails and Logging of the activities done by each agents.

## 2. Requirements
I need
- Challenge me with my design with Trade-offs
- Generate a mermaid diagram
- Document the Tradeoffs
- Document the details if the Design

Do the following
- Create the file under docs

Use the architecture document from `docs/architecture.md`

## 3. Out-of-scope
- Development and coding

