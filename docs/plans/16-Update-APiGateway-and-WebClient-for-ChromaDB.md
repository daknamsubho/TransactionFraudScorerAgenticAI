# Implementation Plan: Update API Gateway and WebClient for ChromaDB (PRD-016)

## Goal Description
Implement full API Gateway and WebClient capabilities to interact with the **ChromaDB Vector Database** per [docs/prds/16-Update-APiGateway-and-WebClient-for-ChromaDB.md](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/docs/prds/16-Update-APiGateway-and-WebClient-for-ChromaDB.md):
1. **OpenAPI v3 Specification**: Add formal ChromaDB Vector DB endpoints to [`docs/openapi-spec/openapi.yaml`](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/docs/openapi-spec/openapi.yaml) under a new `VectorDB` tag:
   - `POST /api/v1/vector/query`: Semantic query with input for Top K (`n_results`), `policy_year` filter (`2025` vs `2026`), and `category` filter.
   - `POST /api/v1/vector/documents`: Upload and ingest new policy documents / text into the collection.
   - `GET /api/v1/vector/stats`: Retrieve collection metrics (total chunks, year breakdown, category distribution).
   - `GET /api/v1/vector/documents`: List recent or ingested policy document chunks.
2. **API Gateway Implementation (`src/api_gateway/`)**:
   - Add Pydantic v2 schemas in [`schemas.py`](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/src/api_gateway/schemas.py).
   - Implement the endpoints in [`app.py`](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/src/api_gateway/app.py) leveraging the modular `src/chromadb/` package.
3. **WebClient UI (`src/web_client/static/`)**:
   - Create a new interactive page: [`vectordb.html`](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/src/web_client/static/vectordb.html) (*Page 6: Vector DB - ChromaDB*).
   - Add "6. Vector DB (ChromaDB)" to the navigation bar across all HTML pages (`index.html`, `queue.html`, `users.html`, `transactions.html`, `scores.html`).
   - Implement query execution, Top-K filter, Year-on-Year policy toggling, result cards with similarity badges, and document upload forms in [`app.js`](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/src/web_client/static/app.js) and [`styles.css`](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/src/web_client/static/styles.css).
4. **Colab Setup Notebook**: Update [`notebooks/colab_setup_and_run.ipynb`](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/notebooks/colab_setup_and_run.ipynb) with ChromaDB API Gateway client test calls.

---

## User Review Required

> [!IMPORTANT]
> **Key Endpoints & UI Design Decisions**:
>
> 1. **ChromaDB API Endpoints**:
>    - `POST /api/v1/vector/query`: Accepts `query` (string), `top_k` (integer, default 3), `policy_year` (optional string, e.g. "2025" or "2026"), and `category` (optional string). Returns an array of matched policy chunks with `clause_id`, `title`, `text`, `similarity_score`, `distance`, and metadata.
>    - `POST /api/v1/vector/documents`: Accepts either raw markdown text (which is automatically parsed into clauses) or structured document fields (`content`, `title`, `policy_year`, `category`).
>    - `GET /api/v1/vector/stats`: Returns live collection statistics (e.g. 26 chunks total, 13 for 2025, 13 for 2026).
> 2. **WebClient Vector DB Explorer (`vectordb.html`)**:
>    - **Collection Stats Card**: Live indicator showing total chunks, 2025 count, 2026 count, and active embedding engine.
>    - **Semantic Search Panel**: Query input with preset test buttons (*"Crypto purchase $3200"*, *"Casino betting $2800"*, *"Velocity burst 3 swipes"*, *"Impossible travel 900 km/h"*), Top-K slider (1 to 10), Policy Year filter, and Category dropdown.
>    - **Results View**: Formatted result cards with similarity percentage badge, clause ID, policy year tag, and expandable JSON metadata.
>    - **Document Ingestion Panel**: Interactive upload form to add new fraud policies with immediate live indexing.

---

## Open Questions

> [!NOTE]
> 1. **Navigation Consistency**: All 5 existing pages currently have a top navigation bar (`1. Submit Transaction` through `5. Transaction Scores`). We will update all 5 pages to include `6. Vector DB (ChromaDB)` so navigation is seamless across the entire application.

---

## Proposed Changes

### OpenAPI Specification

#### [MODIFY] [`docs/openapi-spec/openapi.yaml`](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/docs/openapi-spec/openapi.yaml)
- Add tag: `VectorDB` ("ChromaDB vector database operations for RAG policy retrieval and document ingestion").
- Add path: `/api/v1/vector/query` (POST).
- Add path: `/api/v1/vector/documents` (GET, POST).
- Add path: `/api/v1/vector/stats` (GET).
- Add components/schemas:
  - `VectorQueryRequest`, `VectorQueryResultItem`, `VectorQueryResponse`
  - `VectorDocumentUploadRequest`, `VectorDocumentUploadResponse`
  - `VectorStatsResponse`, `VectorDocumentsListResponse`

---

### API Gateway Layer (`src/api_gateway/`)

#### [MODIFY] [`src/api_gateway/schemas.py`](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/src/api_gateway/schemas.py)
- Define Pydantic models:
  - `VectorQueryRequest`: `query: str`, `top_k: int = 3`, `policy_year: str | None = None`, `category: str | None = None`.
  - `VectorQueryResultItem`: `id: str`, `clause_id: str`, `policy_year: str`, `category: str`, `title: str`, `text: str`, `similarity_score: float`, `distance: float`, `metadata: dict[str, Any]`.
  - `VectorQueryResponse`: `query: str`, `top_k: int`, `total_results: int`, `results: list[VectorQueryResultItem]`.
  - `VectorDocumentUploadRequest`: `content: str`, `title: str | None = None`, `policy_year: str = "2026"`, `category: str = "GENERAL"`.
  - `VectorDocumentUploadResponse`: `status: str`, `message: str`, `chunks_ingested: int`, `collection_count: int`.
  - `VectorStatsResponse`: `collection_name: str`, `total_documents: int`, `chunks_per_year: dict[str, int]`, `categories: list[str]`.

#### [MODIFY] [`src/api_gateway/app.py`](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/src/api_gateway/app.py)
- Implement `/api/v1/vector/query`: Calls `query_fraud_policies()` from `src.chromadb.query_policies`.
- Implement `/api/v1/vector/documents` (POST): Parses content into clause chunks or single chunk and calls `collection.upsert()`.
- Implement `/api/v1/vector/documents` (GET): Retrieves existing documents using `collection.get(limit=limit)`.
- Implement `/api/v1/vector/stats` (GET): Queries collection metadata and counts per policy year.

---

### Web Client Layer (`src/web_client/`)

#### [NEW] [`src/web_client/static/vectordb.html`](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/src/web_client/static/vectordb.html)
Dedicated UI for Vector DB querying and document uploading:
- Top bar and API Gateway base URL synchronizer (shared with all other pages).
- Navigation with active state on "6. Vector DB (ChromaDB)".
- **Collection Status Banner**: Live chunk count, 2025/2026 distribution, and refresh button.
- **Query Panel**:
  - Search query box with quick-load scenario buttons.
  - Controls: Top-K input (1–10), Policy Year select (`All`, `2025`, `2026`), Category select.
  - Search button with loading spinner.
- **Results Container**: Renders query results with match confidence badges, clause IDs, and formatted policy text.
- **Upload / Ingest Panel**: Form to upload a `.md` policy file or paste custom policy text.

#### [MODIFY] Navigation on Existing HTML Pages
- [`index.html`](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/src/web_client/static/index.html)
- [`queue.html`](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/src/web_client/static/queue.html)
- [`users.html`](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/src/web_client/static/users.html)
- [`transactions.html`](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/src/web_client/static/transactions.html)
- [`scores.html`](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/src/web_client/static/scores.html)
  - Add `<a href="vectordb.html" class="nav-link">6. Vector DB (ChromaDB)</a>` to the `<nav class="app-nav">` bar.

#### [MODIFY] [`src/web_client/static/app.js`](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/src/web_client/static/app.js)
- Implement `initVectorDbPage()`:
  - Fetches collection stats on page load.
  - Quick-preset query prompt click handlers.
  - Submits search request to `POST /api/v1/vector/query`.
  - Renders matched policy cards with visual similarity scores.
  - Submits document upload to `POST /api/v1/vector/documents`.

#### [MODIFY] [`src/web_client/static/styles.css`](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/src/web_client/static/styles.css)
- Add CSS rules for vector stats cards, preset prompt buttons, similarity badges (`badge-match-high`, `badge-match-med`), policy clause cards, and upload dropzones.

---

### Colab Setup & Run Notebook

#### [MODIFY] [`notebooks/colab_setup_and_run.ipynb`](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/notebooks/colab_setup_and_run.ipynb)
- In Step 5, add code testing the API Gateway ChromaDB endpoints via HTTP (`httpx.post("http://localhost:8000/api/v1/vector/query")`).

---

### Testing & Verification

#### [MODIFY] [`tests/test_api_gateway.py`](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/tests/test_api_gateway.py)
- Add test cases:
  - `test_vector_stats_endpoint`: Verifies `GET /api/v1/vector/stats`.
  - `test_vector_query_endpoint_yoy`: Verifies `POST /api/v1/vector/query` with Top K and Year filter.
  - `test_vector_document_upload_endpoint`: Verifies `POST /api/v1/vector/documents`.

#### [NEW] [`docs/plans/16-Update-APiGateway-and-WebClient-for-ChromaDB.md`](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/docs/plans/16-Update-APiGateway-and-WebClient-for-ChromaDB.md)
- Save implementation plan per user rules.

---

## Verification Plan

### Automated Tests
1. Run the API Gateway test suite:
   ```bash
   python3 -m pytest tests/test_api_gateway.py -v
   ```
2. Run the full test suite across the repository:
   ```bash
   python3 -m pytest tests/
   ```
3. Validate OpenAPI schema syntax:
   ```bash
   python3 -c "import yaml; yaml.safe_load(open('docs/openapi-spec/openapi.yaml'))"
   ```

### Manual Verification
1. Start the API Gateway (`python3 -m uvicorn api_gateway.app:app --port 8000`) and Web Client (`python3 -m web_client.server --port 3000`).
2. Open `http://localhost:3000/vectordb.html` in browser.
3. Test semantic search with preset queries (verifying 2025 vs 2026 responses).
4. Test uploading a custom policy document.
5. Verify that `docs/architecture.md` remains untouched.
