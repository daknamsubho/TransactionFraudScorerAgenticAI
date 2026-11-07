"""ChromaDB Policy Retrieval Skill (`src/fraud_scorer/skills/policy_retrieval_skill.py`)."""

import asyncio
import importlib.util
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool, tool

from fraud_scorer.models.transaction import Transaction

_SKILLS_DIR = Path(__file__).resolve().parent
_SRC_DIR = _SKILLS_DIR.parent.parent
_CHROMA_MOD_DIR = _SRC_DIR / "chromadb"


def _load_chroma_submodule(module_name: str, file_path: Path) -> Any:
    """Load a module from src/chromadb/ without shadowing the external chromadb package."""
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load ChromaDB helper module from {file_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


_chroma_client_mod = _load_chroma_submodule("_fraud_chroma_client", _CHROMA_MOD_DIR / "client.py")
sys.modules.setdefault("client", _chroma_client_mod)
_chroma_ingest_mod = _load_chroma_submodule("_fraud_chroma_ingest", _CHROMA_MOD_DIR / "ingest_policies.py")
_chroma_query_mod = _load_chroma_submodule("_fraud_chroma_query", _CHROMA_MOD_DIR / "query_policies.py")


def _get_seeded_collection() -> Any:
    """Return the persistent ChromaDB fraud_policies collection, auto-seeding if empty."""
    client = _chroma_client_mod.get_chroma_client()
    collection = _chroma_client_mod.get_or_create_policy_collection(client)
    if collection.count() == 0:
        _chroma_ingest_mod.ingest_policy_documents(collection=collection)
    return collection


@lru_cache(maxsize=128)
def _cached_query_policies(
    query_text: str,
    policy_year: str | None = "2026",
    category: str | None = None,
    n_results: int = 3,
) -> list[dict[str, Any]]:
    """Query ChromaDB with LRU memory caching for recurring merchant/corridor queries."""
    collection = _get_seeded_collection()
    return list(
        _chroma_query_mod.query_fraud_policies(
            query_text=query_text,
            policy_year=policy_year,
            n_results=n_results,
            category=category,
            collection=collection,
        )
    )


@tool
def query_fraud_policies_tool(
    query: str,
    policy_year: str = "2026",
    category: str | None = None,
    n_results: int = 3,
) -> list[dict[str, Any]]:
    """Query ChromaDB vector database for authoritative fraud risk policy clauses.

    Args:
        query: Natural language query describing the transaction MCC, amount, velocity, or geo pattern.
        policy_year: Target policy year ('2025' or '2026'). Defaults to '2026'.
        category: Optional category filter (e.g. 'MCC_RULES', 'VELOCITY', 'GEOLOCATION', 'AMOUNT_ANOMALY').
        n_results: Number of top matching policy clauses to retrieve (default 3).
    """
    return _cached_query_policies(
        query_text=query,
        policy_year=policy_year,
        category=category,
        n_results=n_results,
    )


class PolicyRetrievalSkill:
    """Skill used by DataRetrieverAgent to fetch RAG policy clauses from ChromaDB."""

    name: str = "policy_retrieval_skill"
    description: str = (
        "Retrieves authoritative Year-on-Year (2025 vs 2026) fraud risk policy clauses "
        "from ChromaDB using semantic vector search and metadata filtering."
    )

    def get_langchain_tool(self) -> BaseTool:
        """Return the LangChain @tool adapter for this skill."""
        return query_fraud_policies_tool

    @staticmethod
    def build_transaction_query(transaction: Transaction) -> str:
        """Build a descriptive semantic query from a Transaction's attributes."""
        card_present_str = (
            "card present" if transaction.payment_method.is_card_present else "card not present CNP"
        )
        return (
            f"Transaction amount ${transaction.amount:,.2f} {transaction.currency} "
            f"at merchant {transaction.merchant.name} MCC {transaction.merchant.mcc} "
            f"in {transaction.location.city or 'Unknown'}, {transaction.location.country} "
            f"via {transaction.payment_method.payment_type} ({card_present_str})"
        )

    async def execute(
        self,
        transaction: Transaction,
        policy_year: str | None = "2026",
        n_results: int = 3,
        category: str | None = None,
        custom_query: str | None = None,
    ) -> tuple[list[dict[str, Any]], str]:
        """Execute semantic policy retrieval in a background thread for concurrent async I/O."""
        query_str = custom_query or self.build_transaction_query(transaction)
        policies = await asyncio.to_thread(
            _cached_query_policies,
            query_str,
            policy_year,
            category,
            n_results,
        )
        return policies, query_fraud_policies_tool.name
