# Implementation Plan: Create Vector Database for RAG (PRD-015)

## Goal Description
Implement and automate the **ChromaDB Vector Database** setup for the **Transaction Fraud Scorer Agentic AI** RAG Knowledge Layer according to [docs/prds/15-Create-Vector-DB-for-RAG.md](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/docs/prds/15-Create-Vector-DB-for-RAG.md).

All installation and configuration files will reside in `src/chromadb/`, providing:
1. Automated environment setup (`install_chromadb.sh`, `install_chromadb.py`).
2. Persistent ChromaDB client and collection management (`client.py`) with hybrid embedding fallback (Chroma ONNX default `all-MiniLM-L6-v2` with pluggable `nomic-embed-text` Ollama support).
3. Markdown clause chunking and ingestion (`ingest_policies.py`) that indexes [`docs/policy-docs/fraud-risk-policy-2025.md`](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/docs/policy-docs/fraud-risk-policy-2025.md) and [`docs/policy-docs/fraud-risk-policy-2026.md`](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/docs/policy-docs/fraud-risk-policy-2026.md) into the `fraud_policies` collection with rich metadata (`policy_year`, `clause_id`, `category`, `title`).
4. Interactive testing utility (`query_policies.py`) demonstrating metadata-filtered semantic queries (comparing 2025 vs. 2026 policy chunks).
5. Updates to [`notebooks/colab_setup_and_run.ipynb`](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/notebooks/colab_setup_and_run.ipynb) to include ChromaDB dependency installation, vector database initialization, policy ingestion, and an interactive YoY policy retrieval cell.

Per PRD-015, web client changes are **out-of-scope**.

---

## User Review Required

> [!IMPORTANT]
> **Key Architectural & Installation Decisions**:
>
> 1. **Zero-Failure Embedding Strategy**:
>    - To ensure ChromaDB runs reliably across local workstations, CI/CD runners, and Google Colab (CPU or T4 GPU), the client will use Chroma's built-in ONNX embedding model (`all-MiniLM-L6-v2`) by default, while supporting Ollama `nomic-embed-text` when Ollama is running. This guarantees zero startup failures even if Ollama is not yet started.
> 2. **Persistent Storage Directory**:
>    - The vector database files will be persisted in `src/chromadb/chroma_data/`. An automated initialization script will create and populate this directory cleanly.
> 3. **Package Dependency**:
>    - Add `chromadb>=0.5.0` to `dependencies` in `pyproject.toml` so that standard `pip install -e .` installations include vector database support automatically.

---

## Open Questions

> [!NOTE]
> 1. **Ollama Embedding Model in Colab**: In Google Colab, should the notebook pull `nomic-embed-text` in addition to `llama3.2:3b`, or use the built-in ONNX fast embeddings?
>    *(Recommended: Support both — the script defaults to fast in-process ONNX embeddings for immediate execution and seamlessly detects Ollama embeddings if present).*

---

## Proposed Changes

### Core Package Dependencies

#### [MODIFY] [`pyproject.toml`](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/pyproject.toml)
- Add `"chromadb>=0.5.0"` to the core `dependencies` list.

---

### ChromaDB Vector Database Layer (`src/chromadb/`)

#### [NEW] [`src/chromadb/client.py`](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/src/chromadb/client.py)
Vector database connection factory and collection manager:
- `DEFAULT_CHROMA_DIR`: Resolves to `src/chromadb/chroma_data`.
- `get_chroma_client(persist_directory=...) -> chromadb.PersistentClient`: Returns a thread-safe singleton persistent Chroma client.
- `get_embedding_function()`: Returns a robust embedding function (Ollama `nomic-embed-text` if reachable, falling back to default Chroma ONNX `all-MiniLM-L6-v2`).
- `get_or_create_policy_collection(client, collection_name="fraud_policies") -> chromadb.Collection`: Configures cosine distance metric (`hnsw:space: cosine`).

#### [NEW] [`src/chromadb/ingest_policies.py`](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/src/chromadb/ingest_policies.py)
Document chunking and ingestion engine:
- Parses `docs/policy-docs/fraud-risk-policy-2025.md` and `docs/policy-docs/fraud-risk-policy-2026.md`.
- Extracts individual policy clauses (e.g., `[POL-2025-MCC-6051]`, `[POL-2026-VEL-01]`) with:
  - Document text chunk
  - Metadata: `{"policy_year": "2025"|"2026", "clause_id": str, "category": str, "title": str, "source_file": str}`
  - Deterministic ID (e.g. `pol_2025_mcc_6051`).
- Upserts chunks into the `fraud_policies` Chroma collection.
- Returns ingestion metrics (count of chunks added/updated per year).

#### [NEW] [`src/chromadb/query_policies.py`](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/src/chromadb/query_policies.py)
Semantic retrieval helper for agent integration and debugging:
- `query_fraud_policies(query_text, policy_year=None, n_results=3, category=None)`:
  Queries ChromaDB with optional metadata filtering (`{"policy_year": year}`).
- CLI interface allowing developers to test queries from the terminal (e.g. `python3 -m chromadb.query_policies "Crypto purchase $3200" --year 2026`).

#### [NEW] [`src/chromadb/install_chromadb.py`](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/src/chromadb/install_chromadb.py)
Python installation and initialization runner:
- Verifies `chromadb` library is installed and functional.
- Initializes persistent storage at `src/chromadb/chroma_data`.
- Ingests both 2025 and 2026 policy documents.
- Runs verification queries and prints a summary report.

#### [NEW] [`src/chromadb/install_chromadb.sh`](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/src/chromadb/install_chromadb.sh)
Bash wrapper script:
- Verifies python environment, checks or installs `chromadb`.
- Executes `install_chromadb.py`.

#### [NEW] [`src/chromadb/README.md`](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/src/chromadb/README.md)
Documentation covering architecture, storage layout, CLI usage, and LangChain integration patterns.

---

### Colab Setup & Run Notebook

#### [MODIFY] [`notebooks/colab_setup_and_run.ipynb`](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/notebooks/colab_setup_and_run.ipynb)
- **Cell 8 (Dependency Installation)**: Add `chromadb>=0.5.0` to the `pip install` commands.
- **New Step (Step 5)**: Insert a new section:
  - **Markdown**: `## Step 5: Initialize ChromaDB Vector Database & Ingest Policy Documents (2025 vs 2026)`
  - **Code**: Run `!bash src/chromadb/install_chromadb.sh` and execute a live demonstration comparing how a query (`"Crypto purchase $3,200 London"`) retrieves the 2025 step-up review rule vs. the 2026 automatic decline rule.
- Renumber subsequent steps (Step 6 onwards) so the notebook maintains sequential numbering.

---

### Unit & Integration Testing

#### [NEW] [`tests/test_chromadb.py`](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/tests/test_chromadb.py)
Automated test suite covering:
- Client creation and temporary persistent directory handling.
- Markdown policy document parsing and chunk extraction.
- Upserting chunks into `fraud_policies` collection.
- Metadata filtering (`policy_year: "2025"` vs `policy_year: "2026"`).
- Verified semantic retrieval: Asserting that crypto query retrieves `[POL-2025-MCC-6051]` under 2025 filter and `[POL-2026-MCC-6051]` under 2026 filter.

---

### Project Plans (`docs/plans/`)

#### [NEW] [`docs/plans/15-Create-Vector-DB-for-RAG.md`](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/docs/plans/15-Create-Vector-DB-for-RAG.md)
Save this implementation plan to `docs/plans/` in accordance with project rules.

---

## Verification Plan

### Automated Tests
1. Run the new ChromaDB test suite:
   ```bash
   python3 -m pytest tests/test_chromadb.py -v
   ```
2. Run the full project test suite to ensure no regressions:
   ```bash
   python3 -m pytest tests/
   ```
3. Run the ChromaDB installation and ingestion CLI:
   ```bash
   python3 src/chromadb/install_chromadb.py
   ```
4. Verify notebook validity:
   ```bash
   python3 -c "import json; json.load(open('notebooks/colab_setup_and_run.ipynb'))"
   ```

### Manual Verification
- Verify that `src/chromadb/chroma_data` is initialized with vector index files.
- Verify that querying the vector database with `policy_year=2025` returns 2025 clauses and `policy_year=2026` returns 2026 clauses.
- Verify that `colab_setup_and_run.ipynb` cells are cleanly formatted and runnable.
- Ensure `docs/architecture.md` remains untouched.
