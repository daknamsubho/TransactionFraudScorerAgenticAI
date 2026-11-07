"""Unit and integration tests for ChromaDB Vector Database setup and RAG policy retrieval."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.chromadb.client import (
    DEFAULT_COLLECTION_NAME,
    get_chroma_client,
    get_or_create_policy_collection,
)
from src.chromadb.ingest_policies import (
    DEFAULT_POLICY_DIR,
    ingest_policy_documents,
    parse_policy_markdown,
)
from src.chromadb.query_policies import query_fraud_policies


def test_markdown_policy_parsing() -> None:
    """Verify markdown policy parsing extracts clauses and metadata correctly."""
    policy_2025 = DEFAULT_POLICY_DIR / "fraud-risk-policy-2025.md"
    policy_2026 = DEFAULT_POLICY_DIR / "fraud-risk-policy-2026.md"

    assert policy_2025.exists(), "fraud-risk-policy-2025.md missing"
    assert policy_2026.exists(), "fraud-risk-policy-2026.md missing"

    chunks_2025 = parse_policy_markdown(policy_2025)
    assert len(chunks_2025) >= 5, f"Expected at least 5 chunks for 2025, got {len(chunks_2025)}"

    # Check that metadata has policy_year = 2025
    for c in chunks_2025:
        assert c["metadata"]["policy_year"] == "2025"
        assert "clause_id" in c["metadata"]
        assert len(c["text"]) > 20

    chunks_2026 = parse_policy_markdown(policy_2026)
    assert len(chunks_2026) >= 5, f"Expected at least 5 chunks for 2026, got {len(chunks_2026)}"

    for c in chunks_2026:
        assert c["metadata"]["policy_year"] == "2026"
        assert "clause_id" in c["metadata"]


def test_chroma_client_and_collection_init(tmp_path: Path) -> None:
    """Verify Chroma persistent client and collection initialization."""
    db_dir = tmp_path / "test_chroma_data"
    client = get_chroma_client(db_dir)

    assert db_dir.exists()
    collection = get_or_create_policy_collection(client, collection_name="test_policies")

    assert collection.name == "test_policies"
    assert collection.count() == 0


def test_policy_ingestion_and_yoy_retrieval(tmp_path: Path) -> None:
    """Verify full ingestion of 2025 and 2026 policies and test YoY query divergence."""
    db_dir = tmp_path / "test_chroma_yoy"
    client = get_chroma_client(db_dir)
    collection = get_or_create_policy_collection(client, collection_name=DEFAULT_COLLECTION_NAME)

    summary = ingest_policy_documents(policy_dir=DEFAULT_POLICY_DIR, collection=collection)

    assert summary["status"] == "success"
    assert summary["total_chunks_ingested"] >= 10
    assert summary["chunks_per_year"]["2025"] >= 5
    assert summary["chunks_per_year"]["2026"] >= 5
    assert collection.count() == summary["total_chunks_ingested"]

    # Test 1: Crypto query divergence
    crypto_query = "Cryptocurrency exchange purchase over $3000 MCC 6051"

    res_2025 = query_fraud_policies(crypto_query, policy_year="2025", n_results=1, collection=collection)
    assert len(res_2025) == 1
    assert "POL-2025-MCC-6051" in res_2025[0]["clause_id"]
    assert res_2025[0]["policy_year"] == "2025"

    res_2026 = query_fraud_policies(crypto_query, policy_year="2026", n_results=1, collection=collection)
    assert len(res_2026) == 1
    assert "POL-2026-MCC-6051" in res_2026[0]["clause_id"]
    assert res_2026[0]["policy_year"] == "2026"

    # Test 2: Velocity burst query divergence
    velocity_query = "Rapid transaction burst with 3 transactions in 60 minutes"

    res_vel_2025 = query_fraud_policies(velocity_query, policy_year="2025", n_results=1, collection=collection)
    assert len(res_vel_2025) == 1
    assert "POL-2025-VEL-01" in res_vel_2025[0]["clause_id"]

    res_vel_2026 = query_fraud_policies(velocity_query, policy_year="2026", n_results=1, collection=collection)
    assert len(res_vel_2026) == 1
    assert "POL-2026-VEL-01" in res_vel_2026[0]["clause_id"]


def test_category_metadata_filtering(tmp_path: Path) -> None:
    """Verify filtering by both category and policy_year."""
    db_dir = tmp_path / "test_chroma_filter"
    client = get_chroma_client(db_dir)
    collection = get_or_create_policy_collection(client)
    ingest_policy_documents(DEFAULT_POLICY_DIR, collection)

    geo_results = query_fraud_policies(
        query_text="Impossible flight speed across continents",
        policy_year="2026",
        category="GEOLOCATION",
        n_results=2,
        collection=collection,
    )

    assert len(geo_results) > 0
    for r in geo_results:
        assert r["policy_year"] == "2026"
        assert r["category"] == "GEOLOCATION"
