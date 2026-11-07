"""Semantic Query Utility for ChromaDB Fraud Policies."""

from __future__ import annotations

import argparse
import logging
from typing import Any

from chromadb.api.models.Collection import Collection

try:
    from client import DEFAULT_COLLECTION_NAME, get_chroma_client, get_or_create_policy_collection
except ImportError:
    from src.chromadb.client import DEFAULT_COLLECTION_NAME, get_chroma_client, get_or_create_policy_collection

logger = logging.getLogger("fraud_scorer.chromadb.query")


def query_fraud_policies(
    query_text: str,
    policy_year: str | None = None,
    n_results: int = 3,
    category: str | None = None,
    collection: Collection | None = None,
) -> list[dict[str, Any]]:
    """Query ChromaDB for relevant fraud policies with optional year and category filtering.

    Args:
        query_text: Natural language search string (e.g. "Crypto purchase over $2000 MCC 6051").
        policy_year: Optional filter for policy year ("2025" or "2026").
        n_results: Maximum number of policy chunks to return (default: 3).
        category: Optional category filter (e.g. "MCC_RULES", "VELOCITY", "GEOLOCATION").
        collection: Optional Chroma Collection instance.

    Returns:
        List of matching document dicts with clause_id, policy_year, title, text, and distance.
    """
    if collection is None:
        client = get_chroma_client()
        collection = get_or_create_policy_collection(client)

    # Build metadata where filter
    where_filter: dict[str, Any] | None = None
    if policy_year and category:
        where_filter = {"$and": [{"policy_year": str(policy_year)}, {"category": category}]}
    elif policy_year:
        where_filter = {"policy_year": str(policy_year)}
    elif category:
        where_filter = {"category": category}

    query_kwargs: dict[str, Any] = {
        "query_texts": [query_text],
        "n_results": n_results,
    }
    if where_filter:
        query_kwargs["where"] = where_filter

    results = collection.query(**query_kwargs)

    formatted: list[dict[str, Any]] = []
    if not results or not results["documents"] or not results["documents"][0]:
        return formatted

    documents = results["documents"][0]
    metadatas = results["metadatas"][0] if results["metadatas"] else [{}] * len(documents)
    distances = results["distances"][0] if results["distances"] else [0.0] * len(documents)
    ids = results["ids"][0] if results["ids"] else [""] * len(documents)

    for doc_id, text, meta, dist in zip(ids, documents, metadatas, distances, strict=False):
        # Cosine distance: similarity = 1.0 - distance
        similarity = round(max(0.0, 1.0 - dist), 4) if dist is not None else 1.0
        formatted.append(
            {
                "id": doc_id,
                "clause_id": meta.get("clause_id", "N/A"),
                "policy_year": meta.get("policy_year", "N/A"),
                "category": meta.get("category", "N/A"),
                "title": meta.get("title", "N/A"),
                "text": text,
                "distance": round(dist, 4) if dist is not None else 0.0,
                "similarity_score": similarity,
                "metadata": meta,
            }
        )

    return formatted


def main() -> None:
    """CLI entrypoint for querying policy documents in ChromaDB."""
    parser = argparse.ArgumentParser(description="Query ChromaDB Fraud Policies by semantic similarity.")
    parser.add_argument("query", type=str, help="Search query (e.g., 'Crypto purchase in London')")
    parser.add_argument("--year", type=str, default=None, choices=["2025", "2026"], help="Filter by policy year")
    parser.add_argument("--limit", type=int, default=3, help="Max results to return (default: 3)")
    parser.add_argument("--category", type=str, default=None, help="Filter by category (e.g. MCC_RULES)")
    args = parser.parse_args()

    results = query_fraud_policies(
        query_text=args.query,
        policy_year=args.year,
        n_results=args.limit,
        category=args.category,
    )

    print(f"\n🔍 Search Query: '{args.query}' (Year Filter: {args.year or 'ALL'})")
    print(f"📋 Found {len(results)} matching policy clauses:\n")

    for i, r in enumerate(results, 1):
        print(f"--- Result {i} [Similarity: {r['similarity_score']:.2%}] ---")
        print(f"📌 Clause: {r['clause_id']} | Year: {r['policy_year']} | Category: {r['category']}")
        print(f"🏷️  Title: {r['title']}")
        print(f"📝 Text:\n{r['text']}\n")


if __name__ == "__main__":
    main()
