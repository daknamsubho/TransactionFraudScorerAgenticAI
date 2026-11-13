# Implementation Plan: Implement End-to-End Traceability & Real-Time Agent Streaming (PRD-018)

## Goal Description
Implement a **Dual-Plane Observability Architecture** across the **Transaction Fraud Scorer Agentic AI**:
1. **Plane 1: Real-Time UI Streaming Fast Path (< 1ms latency)**: Stream granular agent execution events (`AgentStepEvent`), tool invocations, and Actor-Critic critique iterations directly from the LangGraph State Machine through FastAPI's [`ConnectionManager`](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/src/api_gateway/websocket_manager.py) to the Web Client over WebSockets.
2. **Plane 2: Deep Distributed Tracing & Telemetry (Asynchronous / Out-of-Band)**: Instrument LangGraph, multi-tier agents, ChromaDB RAG retriever, and SQLite tools with **LangSmith** and optional **OTel Collector** exports, with full client-side PII/PCI-DSS masking.

---

## Architectural Principles & Trade-Off Resolutions

> [!IMPORTANT]
> ### 1. Rejection of the OTel Collector Middleman for WebSockets
> - **Anti-Pattern**: Routing `App -> OTel Collector -> API Gateway Webhook -> WebSocket -> WebClient` introduces reverse coupling loops, 500ms–3000ms batching jitter, and protobuf payload bloat.
> - **Resolution**: In-process streaming directly from LangGraph to FastAPI's WebSocket manager delivers instant (<1ms) live feedback to the browser, while OTel/LangSmith receives asynchronous background traces out-of-band.
> - **Correlation**: The WebSocket event carries `trace_id` / `langsmith_run_id`, allowing the UI to show a live reasoning timeline and a direct link: `[🔍 View Trace in LangSmith]`.

> [!CAUTION]
> ### 2. PCI-DSS & PII Data Sanitization Before Telemetry Dispatch
> - **Security Risk**: Raw cardholder PANs, CVVs, and customer identity fields could inadvertently enter external observability clouds.
> - **Safeguard**: Introduce a dedicated sanitizer module (`src/fraud_scorer/observability/sanitizer.py`) implementing deterministic regex masking for payment tokens, card numbers, addresses, and customer names before attaching inputs/outputs to LangSmith spans.

> [!TIP]
> ### 3. Decoupled Resilience (Zero-Impact when Telemetry is Off)
> - **Behavior**: If `LANGSMITH_TRACING=false` or `LANGSMITH_API_KEY` is omitted, the application must run with **zero network requests to LangSmith** and **< 0.1ms overhead**, while WebSocket streaming continues smoothly.

---

## Proposed Changes

```
src/
├── fraud_scorer/
│   ├── config.py                                 # Add LangSmith & OTel settings
│   ├── observability/
│   │   ├── __init__.py                           # Export tracing utilities & sanitizer
│   │   ├── tracer.py                             # LangSmith & OTel setup, context manager & helper
│   │   └── sanitizer.py                          # Client-side PII/PCI-DSS masking
│   ├── agents/
│   │   ├── workflow.py                           # Add step event callbacks & track iterations
│   │   ├── orchestrator_agent.py                 # Pass run_name, tags, metadata to ainvoke
│   │   ├── data_retriever_agent.py               # Trace SQLite & ChromaDB tool calls
│   │   └── analysis_agent.py                     # Trace modular skill executions
├── sqllite/
│   ├── crud.py                                   # Add langsmith_run_id to insert/select_transaction_score
│   └── database.py                               # DB migration for langsmith_run_id column
├── api_gateway/
│   ├── schemas.py                                # Add AgentStepEvent & AgentStepEventType
│   ├── websocket_manager.py                      # Support AgentStepEvent broadcasting
│   └── app.py                                    # Stream events during scoring & dispatch feedback
├── web_client/
│   └── static/
│       ├── app.js                                # Handle live agent step events & render timeline
│       └── index.html                            # Live Agent Reasoning card & trace link badge
tests/
└── test_langsmith_traceability.py                 # Comprehensive unit & integration tests
```

---

### Phase 1: Configuration & Environment Settings

#### [MODIFY] [config.py](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/src/fraud_scorer/config.py)
- Add LangSmith and OTel configuration variables to `Settings`:
  - `langsmith_tracing: bool = False`
  - `langsmith_endpoint: str = "https://api.smith.langchain.com"`
  - `langsmith_api_key: str | None = None`
  - `langsmith_project: str = "fraud-scorer-agentic-ai"`
  - `langsmith_mask_pii: bool = True`
  - `langsmith_sample_rate: float = 1.0`
  - `otel_exporter_otlp_endpoint: str | None = None`
  - `enable_websocket_trace_streaming: bool = True`
- Add helper method `is_langsmith_enabled() -> bool`.

---

### Phase 2: Observability Plane & PII Sanitizer

#### [NEW] `src/fraud_scorer/observability/__init__.py`
- Package initialization exporting `get_tracer`, `sanitize_payload`, `create_trace_config`, `record_analyst_feedback`.

#### [NEW] `src/fraud_scorer/observability/sanitizer.py`
- Implements:
  - `mask_pan(text: str) -> str`: Replaces 13-19 digit card numbers with masked patterns (`****-****-****-1234`).
  - `sanitize_transaction_payload(data: dict[str, Any]) -> dict[str, Any]`: Recursively scrubs PII fields (PAN, CVV, billing street, IP coordinates) while preserving non-sensitive operational metadata (`amount`, `currency`, `merchant_category_code`, `timestamp`).

#### [NEW] `src/fraud_scorer/observability/tracer.py`
- Implements:
  - `get_langsmith_client() -> langsmith.Client | None`: Thread-safe cached LangSmith client instance.
  - `build_langchain_run_config(tx_id, account_id, policy_year, tags, metadata) -> RunnableConfig`: Constructs the dictionary passed to LangGraph and LangChain runnables.
  - `safe_traceable(name, run_type, ...)`: Wrapper around `langsmith.run_helpers.traceable` that gracefully acts as a no-op when LangSmith is disabled.
  - `record_feedback(run_id, key, score, comment)`: Dispatches feedback scores to LangSmith asynchronously.

---

### Phase 3: WebSocket Event Schemas & Real-Time Streaming (Plane 1)

#### [MODIFY] [schemas.py](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/src/api_gateway/schemas.py)
- Add `AgentStepEventType(str, Enum)`:
  - `STEP_STARTED`, `TOOL_EXECUTED`, `CRITIC_VERDICT`, `STEP_COMPLETED`, `CIRCUIT_BREAKER_TRIGGERED`, `TRANSACTION_SCORED`.
- Add `AgentStepEvent(BaseModel)` with fields:
  - `event_type: str`, `transaction_id: str`, `trace_id: str | None`, `node_name: str`, `status: str`, `elapsed_ms: float`, `retry_count: int`, `message: str`, `details: dict[str, Any]`.

#### [MODIFY] [websocket_manager.py](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/src/api_gateway/websocket_manager.py)
- Update `broadcast_event()` to handle both `WebSocketTransactionEvent` and `AgentStepEvent`.

#### [MODIFY] [workflow.py](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/src/fraud_scorer/agents/workflow.py)
- Support an optional asynchronous step callback: `on_step_event: Callable[[AgentStepEvent], Awaitable[None]] | None = None`.
- In each state node (`data_retrieval_node`, `analysis_node`, `decision_node`, `evaluator_node`, `circuit_breaker_fallback_node`):
  - Emit `STEP_STARTED` at entry.
  - Emit `TOOL_EXECUTED` when tools/skills complete.
  - Emit `CRITIC_VERDICT` when the Evaluator agent accepts or rejects a draft.
  - Emit `STEP_COMPLETED` at exit.

---

### Phase 4: LangGraph Supervisor & Agent Deep Instrumentation (Plane 2)

#### [MODIFY] [orchestrator_agent.py](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/src/fraud_scorer/agents/orchestrator_agent.py)
- In `run_workflow_state()`:
  - Generate parent trace configuration using `build_langchain_run_config()`.
  - Pass sanitized transaction summary into trace metadata.
  - Wire the step callback into `workflow.ainvoke(initial_state, config=run_config)`.
  - Extract and attach `langsmith_run_id` to the returned `FraudAssessment` metadata.

#### [MODIFY] [data_retriever_agent.py](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/src/fraud_scorer/agents/data_retriever_agent.py)
- Wrap SQLite `lookup_account_history` and ChromaDB `PolicyRetrievalSkill` with `@safe_traceable(run_type="retriever" / "tool")` so vector similarity scores and query latencies appear as child spans.

#### [MODIFY] [analysis_agent.py](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/src/fraud_scorer/agents/analysis_agent.py)
- Instrument risk skills (`velocity`, `geo`, `merchant`, `amount`) with child spans recording detected anomalies and contribution scores.

---

### Phase 5: Storage, API Gateway & Web Client UI Updates

#### [MODIFY] [schema.sql](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/docs/rdbms-model-schema/schema.sql) & [crud.py](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/src/sqllite/crud.py)
- Add nullable column `langsmith_run_id TEXT` to the `transaction_scores` table.
- Update `insert_transaction_score()` and `select_transaction_score()` to persist and retrieve `langsmith_run_id`.

#### [MODIFY] [app.py](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/src/api_gateway/app.py)
- In `POST /api/v1/transactions/score`:
  - Pass the gateway's `ConnectionManager.broadcast_event` callback into the orchestrator workflow.
  - Store the `langsmith_run_id` into the SQLite score record.
  - Return `langsmith_run_id` in `ScoreDetails` and `TransactionScoreResponse`.
- In `POST /api/v1/transactions/decision`:
  - Lookup the transaction's `langsmith_run_id`.
  - Dispatch analyst outcome to LangSmith (`record_feedback()`).

#### [MODIFY] [web_client/static/index.html](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/src/web_client/static/index.html) & [app.js](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/src/web_client/static/app.js)
- Add a **Live Agent Reasoning** timeline card to the Web Client UI.
- On receiving `AgentStepEvent`s over WebSocket:
  - Display real-time progress badges for each agent:
    - 🔵 `DataRetrieverAgent`: Fetched account profile & 3 policy clauses (42ms)
    - 🟡 `AnalysisAgent`: Calculated velocity burst & geo haversine distance (115ms)
    - 🟣 `DecisionAgent`: Proposed score 82.5 (DECLINE)
    - 🟢 `EvaluatorAgent`: Verified policy consistency - ACCEPTED (320ms)
  - Display the `[🔍 View Trace in LangSmith]` badge with a link to the LangSmith run.

---

### Phase 6: Testing & Verification Plan

#### [NEW] `tests/test_langsmith_traceability.py`
1. **PII Sanitizer Tests**:
   - Verify 16-digit card numbers, addresses, and CVVs are masked in payloads.
   - Verify unmasked strings never appear in output dictionaries.
2. **Graceful Fallback Tests (Disabled State)**:
   - Run full `OrchestratorAgent.evaluate_transaction()` with `LANGSMITH_TRACING=False`.
   - Verify zero exceptions, identical scoring behavior, and active WebSocket events.
3. **Trace Configuration & Hierarchy Tests**:
   - Mock `langsmith.Client` to verify run trees are created with proper `tags` and `metadata`.
   - Verify node metadata correctly reflects `retry_count`, `policy_year`, and `is_fallback`.
4. **WebSocket Event Streaming Tests**:
   - Mock WebSocket connection and verify `AgentStepEvent` messages are emitted at each node transition.
5. **Analyst Feedback Dispatch Tests**:
   - Test `POST /api/v1/transactions/decision` triggers `record_feedback()` with correct `run_id` and score.

---

## Rollout & Execution Order

1. **Step 1**: Create `src/fraud_scorer/observability/` package with `sanitizer.py` and `tracer.py`.
2. **Step 2**: Update `src/fraud_scorer/config.py` with LangSmith, OTel, and WebSocket streaming settings.
3. **Step 3**: Add `AgentStepEvent` schemas to `src/api_gateway/schemas.py` and update `websocket_manager.py`.
4. **Step 4**: Instrument `workflow.py` with the step-event callback and `orchestrator_agent.py` with LangGraph context propagation.
5. **Step 5**: Instrument `data_retriever_agent.py` and `analysis_agent.py` with child spans.
6. **Step 6**: Update SQLite schema and `src/api_gateway/app.py` for `langsmith_run_id` persistence & analyst feedback.
7. **Step 7**: Update Web Client UI (`index.html` and `app.js`) with the Live Agent Reasoning timeline and LangSmith trace link badge.
8. **Step 8**: Implement unit & integration test suite in `tests/test_langsmith_traceability.py` and run full regression tests.
