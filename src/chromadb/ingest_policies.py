"""Policy Document Ingestion & Chunking Engine for ChromaDB Vector Store."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from chromadb.api.models.Collection import Collection

try:
    from client import DEFAULT_COLLECTION_NAME, get_chroma_client, get_or_create_policy_collection
except ImportError:
    from src.chromadb.client import DEFAULT_COLLECTION_NAME, get_chroma_client, get_or_create_policy_collection

logger = logging.getLogger("fraud_scorer.chromadb.ingest")

CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent.parent
DEFAULT_POLICY_DIR = PROJECT_ROOT / "docs" / "policy-docs"


def parse_policy_markdown(file_path: Path) -> list[dict[str, Any]]:
    """Parse a Markdown policy document into granular, metadata-tagged clause chunks.

    Args:
        file_path: Path to the markdown policy file (e.g., fraud-risk-policy-2025.md).

    Returns:
        List of dictionaries with keys: id, text, metadata.
    """
    content = file_path.read_text(encoding="utf-8")
    filename = file_path.name

    # Determine policy year from filename or metadata header
    year_match = re.search(r"202[5-9]", filename)
    policy_year = year_match.group(0) if year_match else "2026"

    chunks: list[dict[str, Any]] = []

    # 1. Extract Executive Overview & Decision Taxonomy Chunk
    taxonomy_match = re.search(
        r"(## 1\. Executive Policy Framework & Risk Appetite[\s\S]*?)(?=## 2\. Specific Policy Clauses|\Z)",
        content,
    )
    if taxonomy_match:
        tax_text = taxonomy_match.group(1).strip()
        tax_id = f"pol_{policy_year}_taxonomy_overview"
        chunks.append(
            {
                "id": tax_id,
                "text": f"[{policy_year} Fraud Policy Framework & Taxonomy]\n{tax_text}",
                "metadata": {
                    "policy_year": policy_year,
                    "clause_id": f"POL-{policy_year}-TAXONOMY",
                    "category": "TAXONOMY",
                    "title": f"Executive Policy Framework & Risk Appetite {policy_year}",
                    "source_file": filename,
                },
            }
        )

    # 2. Extract specific tagged clauses: #### `[POL-YYYY-CATEGORY-NN]` Title
    clause_pattern = re.compile(
        r"####\s+`\[(POL-\d{4}-([A-Z0-9]+)-\d+)\]`\s+([^\n]+)\n([\s\S]*?)(?=(?:####\s+`\[POL-|\Z|###\s+Section|##\s+3\.))"
    )

    for match in clause_pattern.finditer(content):
        clause_id = match.group(1).strip()
        raw_category = match.group(2).strip()
        title = match.group(3).strip()
        clause_body = match.group(4).strip()

        # Normalize category
        if "MCC" in raw_category:
            category = "MCC_RULES"
        elif "VEL" in raw_category:
            category = "VELOCITY"
        elif "GEO" in raw_category:
            category = "GEOLOCATION"
        elif "AMT" in raw_category:
            category = "AMOUNT_ANOMALY"
        elif "PCI" in raw_category or "DEV" in raw_category:
            category = "DEVICE_SECURITY"
        else:
            category = raw_category

        full_text = f"Policy Clause: [{clause_id}] {title} ({policy_year})\n{clause_body}"
        chunk_id = f"pol_{policy_year}_{clause_id.lower().replace('-', '_')}"

        chunks.append(
            {
                "id": chunk_id,
                "text": full_text,
                "metadata": {
                    "policy_year": policy_year,
                    "clause_id": clause_id,
                    "category": category,
                    "title": title,
                    "source_file": filename,
                },
            }
        )

    # 3. Extract Adverse Action & Explainability guidelines (Section 3)
    adverse_match = re.search(
        r"(## 3\. Mandatory Explainability & Adverse Action Guidelines[\s\S]*?)\Z",
        content,
    )
    if adverse_match:
        adverse_text = adverse_match.group(1).strip()
        chunks.append(
            {
                "id": f"pol_{policy_year}_adverse_action_rules",
                "text": f"[{policy_year} Adverse Action & Explainability Mandates]\n{adverse_text}",
                "metadata": {
                    "policy_year": policy_year,
                    "clause_id": f"POL-{policy_year}-ADVERSE-ACTION",
                    "category": "COMPLIANCE",
                    "title": f"Mandatory Explainability Guidelines {policy_year}",
                    "source_file": filename,
                },
            }
        )

    return chunks


def ingest_policy_documents(
    policy_dir: Path | str | None = None,
    collection: Collection | None = None,
) -> dict[str, Any]:
    """Ingest all markdown policy files from policy_dir into the ChromaDB collection.

    Args:
        policy_dir: Directory containing policy markdown files (defaults to docs/policy-docs).
        collection: Optional target collection; creates default if None.

    Returns:
        Summary dictionary with ingestion metrics.
    """
    target_dir = Path(policy_dir) if policy_dir else DEFAULT_POLICY_DIR
    if not target_dir.exists():
        raise FileNotFoundError(f"Policy directory does not exist: {target_dir}")

    if collection is None:
        client = get_chroma_client()
        collection = get_or_create_policy_collection(client)

    policy_files = sorted(target_dir.glob("fraud-risk-policy-*.md"))
    if not policy_files:
        logger.warning("No policy markdown files matching 'fraud-risk-policy-*.md' found in %s", target_dir)

    all_chunks: list[dict[str, Any]] = []
    for p_file in policy_files:
        parsed = parse_policy_markdown(p_file)
        all_chunks.extend(parsed)

    if not all_chunks:
        return {"status": "empty", "total_chunks": 0, "files_processed": []}

    # Upsert into ChromaDB
    ids = [chunk["id"] for chunk in all_chunks]
    documents = [chunk["text"] for chunk in all_chunks]
    metadatas = [chunk["metadata"] for chunk in all_chunks]

    collection.upsert(
        ids=ids,
        documents=documents,
        metadatas=metadatas,
    )

    summary = {
        "status": "success",
        "total_chunks_ingested": len(all_chunks),
        "files_processed": [f.name for f in policy_files],
        "collection_count": collection.count(),
        "chunks_per_year": {
            "2025": sum(1 for c in all_chunks if c["metadata"].get("policy_year") == "2025"),
            "2026": sum(1 for c in all_chunks if c["metadata"].get("policy_year") == "2026"),
        },
    }
    logger.info("Ingestion complete: %s", summary)
    return summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    res = ingest_policy_documents()
    print("✅ Policy Ingestion Summary:")
    for k, v in res.items():
        print(f"  • {k}: {v}")
