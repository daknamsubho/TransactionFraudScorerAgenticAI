# ChromaDB Vector Store for Transaction Fraud Scorer RAG

This directory contains the ChromaDB Vector Database setup, collection management, and ingestion tooling for the **Transaction Fraud Scorer Agentic AI** RAG Knowledge Layer.

---

## 1. Directory Structure

```text
src/chromadb/
├── client.py               # PersistentClient factory & hybrid embedding provider
├── ingest_policies.py      # Markdown policy chunker & vector upsert engine
├── query_policies.py       # Semantic query utility with YoY metadata filtering
├── install_chromadb.py     # Python setup and verification entrypoint
├── install_chromadb.sh     # Bash installation and setup wrapper
├── chroma_data/            # Persistent vector database storage directory
└── README.md               # This documentation
```

---

## 2. Quickstart

### Automated Installation & Initialization (CLI)
Run the automated setup script to verify dependencies, create the vector store at `src/chromadb/chroma_data`, and ingest the Year-on-Year policies:

```bash
# Using Bash wrapper
./src/chromadb/install_chromadb.sh

# Or using Python directly
python3 src/chromadb/install_chromadb.py
```

### Querying Fraud Policies via CLI
You can test semantic vector retrieval directly from the terminal, with optional YoY policy filtering:

```bash
# Query 2026 policy for high-value crypto
python3 src/chromadb/query_policies.py "Crypto purchase over $3000 in London" --year 2026

# Query 2025 policy for the same transaction
python3 src/chromadb/query_policies.py "Crypto purchase over $3000 in London" --year 2025
```

---

## 3. Python API Integration

### Getting the Chroma Client & Collection
```python
from chromadb.client import get_chroma_client, get_or_create_policy_collection

client = get_chroma_client()
collection = get_or_create_policy_collection(client)
print(f"Total policy chunks: {collection.count()}")
```

### Performing Metadata-Filtered Semantic Retrieval
```python
from chromadb.query_policies import query_fraud_policies

# Retrieve applicable clauses under the 2026 policy
results = query_fraud_policies(
    query_text="Card-not-present online casino betting over $2000",
    policy_year="2026",
    n_results=2,
)

for r in results:
    print(f"Clause: {r['clause_id']} | Similarity: {r['similarity_score']:.2%}")
    print(f"Text: {r['text']}\n")
```

---

## 4. Embedding Strategy

The system utilizes a **Zero-Dependency Hybrid Embedding Strategy**:
1. **Default (Zero-Dependency)**: Chroma's built-in ONNX `all-MiniLM-L6-v2` embedding function. Runs locally in-process without requiring external daemon processes or GPU hardware.
2. **Ollama (Optional)**: If `OLLAMA_HOST` is accessible and `USE_OLLAMA_EMBEDDINGS=true`, uses `nomic-embed-text` via `OllamaEmbeddingFunction`.
