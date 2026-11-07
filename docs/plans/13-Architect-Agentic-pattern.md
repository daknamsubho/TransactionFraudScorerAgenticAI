# Implementation Plan: Architect Agentic Pattern (PRD-013)

## Goal Description
Architect and formally document the hybrid multi-agent pattern for the **Transaction Fraud Scorer Agentic AI** system according to [docs/prds/13-Architect-Agentic-pattern.md](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/docs/prds/13-Architect-Agentic-pattern.md) and [docs/architecture.md](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/docs/architecture.md).

The proposed system features:
1. **Supervisor Orchestrator Agent**: Manages the evaluation workflow, delegating to Data Retrieval and Analysis.
2. **Data Retrieval Agent**: Enriches transaction context from databases, MCP tools, and RAG knowledge bases.
3. **Analysis Agent**: Evaluates fraud signals, anomaly metrics, and typologies, with the capability to request additional data from the Data Retrieval Agent.
4. **Decision Agent**: Computes the composite risk score (`0.0 - 100.0`) and recommends a disposition (`APPROVE`, `REVIEW`, `DECLINE`).
5. **Evaluator Agent**: Assesses the validity, explainability, policy alignment, and risk consistency of the Decision Agent's output; triggers a feedback loop back to the Orchestrator for refinement (up to a hard limit of 3 retries).
6. **Omnipresent Cross-Cutting Agents**:
   - **Governance Agent**: Policy guardrails, PII masking, regulatory compliance, and ethical fairness checks.
   - **Observability Agent**: Continuous tracing, execution telemetry, anomaly logging, latency, and model drift detection.

Per PRD-013, implementation code is **out-of-scope**; this deliverable consists of the architecture specification, critical trade-off challenges, architectural failure modes, mitigation strategies, and Mermaid sequence and component diagrams.

---

## User Review Required

> [!IMPORTANT]
> **Key Architectural Challenges & Trade-offs to Review**:
>
> 1. **Direct Agent-to-Agent Coupling (Analysis -> Data Retrieval) vs. Strict Supervisor Loop**:
>    - *Challenge*: Allowing the `Analysis Agent` to directly call the `Data Retrieval Agent` violates strict supervisor isolation, risks circular dependency chains, and bypasses centralized state management.
>    - *Recommended Approach*: Implement a **Hybrid Sub-Orchestration / Tool-Call Abstraction**: The Orchestrator retains state governance via LangGraph conditional routing, but the Analysis Agent has access to a structured callback tool (e.g., `request_additional_data(query)`) that is dispatched to the Data Retrieval Agent under supervisor awareness.
>
> 2. **Evaluator Feedback Loop & Latency SLA (Max 3 Retries)**:
>    - *Challenge*: In online fraud scoring (where p95 latency targets are typically 300ms–1500ms), running up to 3 full re-evaluations (Analysis -> Decision -> Evaluator) can introduce 8–20 seconds of latency and substantial LLM token consumption.
>    - *Recommended Approach*: Implement a **Targeted Differential Feedback Loop** with a strict Latency Circuit Breaker:
>      - Evaluator output specifies *exact failure reasons* (e.g., `MISSING_EVIDENCE`, `ARITHMETIC_MISMATCH`, `POLICY_VIOLATION`), allowing the Supervisor to re-invoke *only* the failing node (e.g., re-score without re-fetching all data).
>      - If timeout deadline (e.g., 2000ms) approaches, fallback immediately to a deterministic heuristic risk score with manual `REVIEW` disposition.
>
> 3. **Omnipresent Governance & Observability Architecture (Middleware Interceptors vs. Autonomous LLMs)**:
>    - *Challenge*: If Governance and Observability are implemented as full LLM agents invoked synchronously before and after *every* agent interaction, a single transaction will incur 10+ sequential LLM round-trips.
>    - *Recommended Approach*: **Dual-Plane Architecture**:
>      - **Synchronous Fast Path (Control Plane Interceptors)**: Deterministic middleware hooks (PII regex/Presidio masking, schema validation, OpenTelemetry distributed tracing) running with sub-millisecond overhead.
>      - **Asynchronous Deep Path (Agent Plane)**: Asynchronous Governance & Observability agents processing telemetry streams out-of-band for compliance auditing, policy violation alerts, and continuous evaluation drift detection.

---

## Open Questions

> [!NOTE]
> 1. **Documentation Placement**: Should the detailed agentic pattern document be written to a dedicated new file: [`docs/agentic-architecture-pattern.md`](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/docs/agentic-architecture-pattern.md), with cross-links integrated into [`docs/architecture.md`](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/docs/architecture.md)? (Recommended: Yes, to maintain clean modular documentation while preserving the existing overarching system architecture).
> 2. **Target Execution Environment**: Should the architecture define two distinct operational modes:
>    - **Online Synchronous Mode**: Max 1 evaluator retry, aggressive timeout, fast deterministic guardrails.
>    - **Nearline / Offline Batch Mode**: Full 3 evaluator retries, full deep governance LLM audit.

---

## Proposed Changes

### Documentation Layer (`docs/`)

#### [NEW] [`docs/agentic-architecture-pattern.md`](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/docs/agentic-architecture-pattern.md)
Create a comprehensive architectural blueprint detailing:
- **Executive Pattern Summary**: Hybrid Supervisor with Actor-Critic Feedback and Omnipresent Cross-Cutting Planes.
- **Architectural Role Specifications**:
  - `Orchestrator Agent` (Supervisor, State Machine Coordinator)
  - `Data Retrieval Agent` (Data ingestion, MCP tool binding, RAG context builder)
  - `Analysis Agent` (Anomaly computation, risk factor formulation, dynamic retrieval requestor)
  - `Decision Agent` (Actor / Hypothesis generator, score normalizer)
  - `Evaluator Agent` (Critic / Quality verifier, consistency auditor, feedback emitter)
  - `Governance Agent` (Omnipresent guardrails, PII scrubber, ethical & compliance validator)
  - `Observability Agent` (Omnipresent telemetry aggregator, latency tracker, trace collector)
- **Architectural Diagrams (Mermaid)**:
  1. **Component & Plane Interaction Diagram**: Showing Control Plane, Agent Execution Plane, and Cross-Cutting Plane.
  2. **Detailed Sequence Diagram**: End-to-end execution flow including initial retrieval, analysis, on-demand supplementary retrieval, decisioning, evaluation, and conditional retry loop (up to 3 iterations) with circuit breakers.
- **Critical Trade-Off & Challenge Analysis**:
  - Supervisor vs. Peer-to-Peer Agent Communication.
  - Evaluation Feedback Loops vs. Production Latency & Cost SLAs.
  - Omnipresent LLM Agent overhead vs. Deterministic Interceptor Middleware.
  - Retry Termination & Convergence Guarantees (preventing ping-pong hallucinations).
- **State Graph Specification (LangGraph Alignment)**:
  - State schema definition (`FraudState`: transaction, profile, risk factors, draft assessment, evaluation feedback, retry count).
  - Transition logic and conditional edges.
- **Failure Modes & Resilience Matrix**:
  - Handling Evaluator Rejection exhausted after 3 retries.
  - Tool timeout or partial retrieval failure.
  - Governance block / PII violation handling.

#### [MODIFY] [`docs/architecture.md`](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/docs/architecture.md)
- Update Section 1 & Section 2 to reference the new Agentic Architecture Pattern and incorporate the Evaluator Agent and omnipresent cross-cutting planes into the roadmap and system topology.
- Add explicit link to [`docs/agentic-architecture-pattern.md`](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/docs/agentic-architecture-pattern.md).

#### [NEW] [`docs/plans/13-Architect-Agentic-pattern.md`](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/docs/plans/13-Architect-Agentic-pattern.md)
- Store this implementation plan under `docs/plans` in compliance with user rules.

---

## Verification Plan

### Automated Verification
- Verify Mermaid diagram rendering and markdown formatting using command line checks or markdown parser validation.
  ```bash
  # Check markdown files syntax and ensure valid formatting
  python3 -c "
  import re
  with open('docs/agentic-architecture-pattern.md', 'r') as f:
      content = f.read()
  assert '```mermaid' in content, 'Mermaid block missing'
  assert 'Evaluator' in content, 'Evaluator agent missing'
  assert 'Governance' in content, 'Governance agent missing'
  assert 'Observability' in content, 'Observability agent missing'
  print('Doc verification successful!')
  "
  ```

### Manual Verification
- Review the architecture document to ensure all requirements of PRD-013 are met:
  1. The architect's design is thoroughly challenged with concrete trade-offs documented.
  2. Mermaid diagrams accurately portray the supervisor flow, evaluator retry loop (max 3), on-demand analysis data requests, and omnipresent cross-cutting agents.
  3. Clear architectural mitigation strategies are provided for latency, cost, and state-drift risks.
