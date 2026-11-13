# Implementation Plan: LLM Model Changes (PRD-019)

## Goal Description
In `PRD-017` / `docs/plans/17-Update-Agents.md`, we implemented Heterogeneous Model Tiering across the LangGraph multi-agent architecture:
- **Tier 1 (Fast SLM)**: `llama3.2:3b` for `DataRetrieverAgent` (SQLite & ChromaDB tool calling)
- **Tier 2 (Analytical LLM)**: `llama3.1:8b` for `AnalysisAgent` (multi-vector signal correlation)
- **Tier 3 (Deep Reasoning & Critical Auditor)**: `qwen3.8:27b` for `DecisionAgent` (Actor) and `EvaluatorAgent` (Critic)

Running `qwen3.8:27b` (a 17 GB model) introduces significant inference latency (>800ms per step, compounded across Actor-Critic critique loops), high VRAM requirements, and lengthy download times in Google Colab and local environments.

**PRD-019 Objective**: Replace `qwen3.8:27b` with `llama3.1:8b` as the default Tier 3 model for `DecisionAgent` and `EvaluatorAgent` while **preserving the Heterogeneous Tier system and `AgentModelConfig` modularity**. This proves the configurability and agility of the agentic architecture and ensures responsive, low-latency execution in local and Colab environments.

---

## Architectural Principles & Trade-Off Resolutions

> [!IMPORTANT]
> ### 1. Preserving Tier Architecture & Configurability
> - **Principle**: The 4-tier conceptual separation (`data_retrieval_model`, `analysis_model`, `decision_model`, `evaluator_model`) remains distinct in `AgentModelConfig`.
> - **Decoupling**: Agent code never hardcodes model tags; agents always read their assigned tier from `model_config` or `settings`.
> - **Configurability**: Operators can switch any tier back to larger frontier models (`qwen3.8:27b`, `llama3.3:70b`, cloud endpoints) via `.env` or constructor arguments without code changes.

> [!TIP]
> ### 2. Colab VRAM & Performance Optimization
> - **Bandwidth & Storage**: Eliminates the 17 GB `qwen3.8:27b` pull in Colab. Pulling `llama3.2:3b` (2.0 GB) and `llama3.1:8b` (4.9 GB) satisfies all agent tiers, saving ~12 GB of disk and reducing model download time from ~10 minutes to under 2 minutes.
> - **Inference Speed**: `llama3.1:8b` reduces evaluation latency from ~800–1500ms down to ~250–400ms per step, keeping Actor-Critic loops comfortably within the 1800ms circuit breaker timeout.

---

## Proposed Changes

```
src/
└── fraud_scorer/
    ├── config.py                       # Update AgentModelConfig & Settings defaults to llama3.1:8b
    └── agents/
        ├── decision_agent.py           # Update docstrings and prompt references
        ├── evaluator_agent.py          # Update docstrings and prompt references
        └── orchestrator_agent.py       # Update demo text and logging
notebooks/
└── colab_setup_and_run.ipynb           # Update Step 5 (model pulls) and Step 8 (orchestrator init)
tests/
└── test_agents_and_skills.py           # Update default tier assertions to llama3.1:8b
```

---

### Phase 1: Configuration Updates

#### [MODIFY] [config.py](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/src/fraud_scorer/config.py)
- In `AgentModelConfig`:
  - Change `decision_model` default from `"qwen3.8:27b"` to `"llama3.1:8b"`
  - Change `evaluator_model` default from `"qwen3.8:27b"` to `"llama3.1:8b"`
  - Update field descriptions to reflect `Llama 3.1 8B`
- In `Settings`:
  - Change `decision_model: str = "llama3.1:8b"`
  - Change `evaluator_model: str = "llama3.1:8b"`
  - Update `resolve_ollama_model()` docstrings

---

### Phase 2: Agent Docstrings & System Prompts

#### [MODIFY] [decision_agent.py](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/src/fraud_scorer/agents/decision_agent.py)
- Update module docstring: replace `qwen3.8:27b` reference with `llama3.1:8b`
- Update `DECISION_AGENT_SYSTEM_PROMPT`: `"You are the Decision Agent (Actor — Tier 3 Reasoning LLM)..."`
- Update `_get_resolved_model()` docstring

#### [MODIFY] [evaluator_agent.py](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/src/fraud_scorer/agents/evaluator_agent.py)
- Update module docstring: replace `qwen3.8:27b` reference with `llama3.1:8b`
- Update `EVALUATOR_AGENT_SYSTEM_PROMPT`: `"You are the Evaluator Agent (Critic — Tier 3 Critical Auditor)..."`
- Update `_get_resolved_model()` docstring

#### [MODIFY] [orchestrator_agent.py](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/src/fraud_scorer/agents/orchestrator_agent.py)
- Update module docstring referencing Tier 3 models
- Update `_async_demo()` display text

---

### Phase 3: Colab Interactive Notebook Updates

#### [MODIFY] [colab_setup_and_run.ipynb](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/notebooks/colab_setup_and_run.ipynb)
- **Cell 0 (Intro Markdown)**:
  - Update step 5 description: `Pull Heterogeneous Model Tiers into Ollama (llama3.2:3b, llama3.1:8b)`.
- **Cell 9 (Step 5 Markdown)**:
  - Update header to: `## Step 5: Pull Heterogeneous Open-Source Models (llama3.2:3b, llama3.1:8b)`.
  - Update bullet points:
    - Tier 1 (`llama3.2:3b`): Fast SLM for `DataRetrieverAgent`
    - Tier 2 (`llama3.1:8b`): Analytical LLM for `AnalysisAgent`
    - Tier 3 (`llama3.1:8b`): Reasoning & Critical Auditor LLM for `DecisionAgent` (Actor) and `EvaluatorAgent` (Critic)
- **Cell 10 (Step 5 Code)**:
  - Remove `!ollama pull qwen3.8:27b` (saves ~17 GB download in Colab).
  - Note that `llama3.1:8b` serves both Tier 2 and Tier 3 while preserving independent tier configuration.
- **Cell 15 (Step 8 Markdown)**:
  - Update Tier 3 description to `llama3.1:8b`.
- **Cell 16 (Step 8 Code & Output)**:
  - Update `AgentModelConfig` instantiation:
    ```python
    model_tiers = AgentModelConfig(
        data_retrieval_model="llama3.2:3b",
        analysis_model="llama3.1:8b",
        decision_model="llama3.1:8b",
        evaluator_model="llama3.1:8b",
    )
    ```

---

### Phase 4: Test Suite Updates & Verification

#### [MODIFY] [test_agents_and_skills.py](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/tests/test_agents_and_skills.py)
- In `test_individual_agents_pipeline()`:
  - Update assertion from `assert decider.model_name == "qwen3.8:27b"` to `"llama3.1:8b"`
  - Update assertion from `assert evaluator.model_name == "qwen3.8:27b"` to `"llama3.1:8b"`

---

## Verification Plan

### Automated Tests
Run the full test suite and code quality checks:
```bash
# 1. Run unit tests for agents and model configuration
uv run pytest tests/test_agents_and_skills.py -v

# 2. Run full regression test suite (all 67 tests)
uv run pytest

# 3. Verify code style and formatting
uv run ruff check src tests

# 4. Verify notebook JSON structure and validity
python3 -c "import json; json.load(open('notebooks/colab_setup_and_run.ipynb'))"
```

### Manual Verification
1. Inspect `notebooks/colab_setup_and_run.ipynb` cells to verify clean markdown rendering and correct model configuration commands.
2. Verify that running `OrchestratorAgent()` without arguments resolves `decision_model` and `evaluator_model` to `llama3.1:8b`.
