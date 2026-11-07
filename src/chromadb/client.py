"""ChromaDB Client & Collection Management for Transaction Fraud Scorer RAG."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import chromadb
from chromadb.api import ClientAPI
from chromadb.api.models.Collection import Collection
from chromadb.config import Settings

logger = logging.getLogger("fraud_scorer.chromadb")

CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent.parent
DEFAULT_CHROMA_DIR = CURRENT_DIR / "chroma_data"
DEFAULT_COLLECTION_NAME = "fraud_policies"

_CLIENT_INSTANCE: ClientAPI | None = None


def get_embedding_function() -> Any:
    """Get the embedding function for ChromaDB.

    Prefers Ollama `nomic-embed-text` if OLLAMA_HOST is reachable and configured,
    otherwise gracefully falls back to Chroma's built-in ONNX DefaultEmbeddingFunction
    (all-MiniLM-L6-v2) for zero-dependency execution.
    """
    ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    use_ollama = os.getenv("USE_OLLAMA_EMBEDDINGS", "false").lower() in ("true", "1", "yes")

    if use_ollama:
        try:
            import httpx

            resp = httpx.get(f"{ollama_host}/api/tags", timeout=1.0)
            if resp.status_code == 200:
                from chromadb.utils.embedding_functions import OllamaEmbeddingFunction

                logger.info("Using OllamaEmbeddingFunction (nomic-embed-text) at %s", ollama_host)
                return OllamaEmbeddingFunction(
                    model_name="nomic-embed-text",
                    url=ollama_host,
                )
        except Exception as exc:
            logger.debug("Ollama embedding probe failed (%s), using ONNX default", exc)

    # Fast in-process ONNX embedding function (no server required)
    from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

    return DefaultEmbeddingFunction()


def get_chroma_client(persist_directory: str | Path | None = None) -> ClientAPI:
    """Return a thread-safe PersistentClient instance pointing to the vector database directory.

    Args:
        persist_directory: Target directory for Chroma storage. Defaults to src/chromadb/chroma_data.
    """
    target_dir = Path(persist_directory) if persist_directory else DEFAULT_CHROMA_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    return chromadb.PersistentClient(
        path=str(target_dir),
        settings=Settings(
            anonymized_telemetry=False,
            allow_reset=True,
        ),
    )


def get_or_create_policy_collection(
    client: ClientAPI | None = None,
    collection_name: str = DEFAULT_COLLECTION_NAME,
    embedding_function: Any | None = None,
) -> Collection:
    """Retrieve or create the fraud policies Chroma collection with cosine similarity.

    Args:
        client: Optional Chroma client instance; if None, creates default client.
        collection_name: Name of the collection (default: 'fraud_policies').
        embedding_function: Optional embedding function. If None, uses get_embedding_function().
    """
    if client is None:
        client = get_chroma_client()

    emb_fn = embedding_function or get_embedding_function()

    return client.get_or_create_collection(
        name=collection_name,
        embedding_function=emb_fn,
        metadata={"hnsw:space": "cosine", "description": "Transaction Fraud Scoring Policies & Bulletins"},
    )
