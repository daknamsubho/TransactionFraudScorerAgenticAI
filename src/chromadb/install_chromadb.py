"""Installation, initialization & verification script for ChromaDB Vector Store."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent.parent

# Ensure src is on sys.path
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

try:
    from client import DEFAULT_CHROMA_DIR, get_chroma_client, get_or_create_policy_collection
    from ingest_policies import DEFAULT_POLICY_DIR, ingest_policy_documents
    from query_policies import query_fraud_policies
except ImportError:
    from src.chromadb.client import DEFAULT_CHROMA_DIR, get_chroma_client, get_or_create_policy_collection
    from src.chromadb.ingest_policies import DEFAULT_POLICY_DIR, ingest_policy_documents
    from src.chromadb.query_policies import query_fraud_policies


def setup_and_verify_chromadb(
    persist_dir: str | Path = DEFAULT_CHROMA_DIR,
    policy_dir: str | Path = DEFAULT_POLICY_DIR,
) -> dict[str, object]:
    """Initialize ChromaDB storage, ingest policy documents, and verify YoY query retrieval.

    Args:
        persist_dir: Path to Chroma persistent database directory.
        policy_dir: Path to markdown policy documents directory.

    Returns:
        Summary dictionary with Chroma status, ingested chunks, and query test results.
    """
    import chromadb

    chroma_ver = chromadb.__version__
    print(f"📦 ChromaDB version: {chroma_ver}")

    # 1. Initialize client & collection
    client = get_chroma_client(persist_dir)
    collection = get_or_create_policy_collection(client)
    print(f"🗄️  Initialized ChromaDB at: {persist_dir}")

    # 2. Ingest policy markdown documents
    print(f"📥 Ingesting policy documents from: {policy_dir}")
    ingest_summary = ingest_policy_documents(policy_dir, collection)
    print(
        f"✅ Ingested {ingest_summary['total_chunks_ingested']} policy chunks "
        f"(2025: {ingest_summary['chunks_per_year']['2025']}, 2026: {ingest_summary['chunks_per_year']['2026']})"
    )

    # 3. Verification test: Query identical query against 2025 vs 2026
    test_query = "Cryptocurrency exchange purchase over $2500 MCC 6051"
    print(f"\n🧪 Running YoY Verification Test: '{test_query}'")

    res_2025 = query_fraud_policies(test_query, policy_year="2025", n_results=1, collection=collection)
    clause_2025 = res_2025[0]["clause_id"] if res_2025 else "NONE"
    sim_2025 = res_2025[0]["similarity_score"] if res_2025 else 0.0
    print(f"  • 2025 Policy Match: {clause_2025} (Similarity: {sim_2025:.2%})")

    res_2026 = query_fraud_policies(test_query, policy_year="2026", n_results=1, collection=collection)
    clause_2026 = res_2026[0]["clause_id"] if res_2026 else "NONE"
    sim_2026 = res_2026[0]["similarity_score"] if res_2026 else 0.0
    print(f"  • 2026 Policy Match: {clause_2026} (Similarity: {sim_2026:.2%})")

    return {
        "chromadb_version": chroma_ver,
        "persist_dir": str(persist_dir),
        "collection_name": collection.name,
        "total_documents": collection.count(),
        "ingest_summary": ingest_summary,
        "verification_test": {
            "query": test_query,
            "match_2025": clause_2025,
            "match_2026": clause_2026,
            "verified": "POL-2025-MCC-6051" in clause_2025 and "POL-2026-MCC-6051" in clause_2026,
        },
    }


def main() -> None:
    """CLI entrypoint for ChromaDB setup & installation."""
    parser = argparse.ArgumentParser(description="Initialize ChromaDB Vector Store & Ingest Fraud Policies.")
    parser.add_argument(
        "--persist-dir",
        default=str(DEFAULT_CHROMA_DIR),
        help=f"Path to Chroma storage directory (default: {DEFAULT_CHROMA_DIR})",
    )
    parser.add_argument(
        "--policy-dir",
        default=str(DEFAULT_POLICY_DIR),
        help=f"Path to policy docs directory (default: {DEFAULT_POLICY_DIR})",
    )
    args = parser.parse_args()

    info = setup_and_verify_chromadb(args.persist_dir, args.policy_dir)
    if info["verification_test"]["verified"]:
        print("\n🎉 ChromaDB Vector Database setup & YoY policy verification SUCCESSFUL!")
    else:
        print("\n⚠️  ChromaDB initialized but verification query returned unexpected clauses.")


if __name__ == "__main__":
    main()
