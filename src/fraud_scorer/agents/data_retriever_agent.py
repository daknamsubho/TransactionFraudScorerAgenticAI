"""Data Retriever Agent (`src/fraud_scorer/agents/data_retriever_agent.py`).

Implements the Single Unified Retrieval Agent with Concurrent I/O (SQLite + ChromaDB)
using a Tier 1 Fast SLM (`llama3.2:3b`) as specified in `docs/agentic-architecture-pattern.md`
with child span instrumentation (`@safe_traceable`) per PRD-018.
"""

import asyncio
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama
from pydantic import BaseModel, Field

from fraud_scorer.config import resolve_ollama_model, settings
from fraud_scorer.models.transaction import RiskFactor, Transaction
from fraud_scorer.observability.tracer import safe_traceable
from fraud_scorer.skills.account_history_skill import AccountHistorySkill
from fraud_scorer.skills.policy_retrieval_skill import PolicyRetrievalSkill

DATA_RETRIEVER_SYSTEM_PROMPT = (
    "You are the Data Retriever Agent (Tier 1 Fast SLM) in a multi-agent financial fraud detection system.\n"
    "Your responsibility is to concurrently retrieve:\n"
    "1. The customer's relational account history, profile age, prior disputes, historical average spend, "
    "and trust tier from SQLite using `lookup_account_history_tool`.\n"
    "2. Relevant organizational fraud risk policy clauses from ChromaDB using `query_fraud_policies_tool`.\n"
    "You also respond to targeted supplementary data requests routed by the Supervisor from the Analysis Agent.\n"
    "Do NOT make any final fraud approval or decline decisions."
)


class DataRetrievalResult(BaseModel):
    """Structured output returned by the Data Retriever Agent to the Orchestrator Agent."""

    account_id: str
    account_history: dict[str, Any] = Field(default_factory=dict)
    rag_policies: list[dict[str, Any]] = Field(default_factory=list)
    supplementary_data: list[dict[str, Any]] = Field(default_factory=list)
    risk_factors: list[RiskFactor] = Field(default_factory=list)
    tools_invoked: list[str] = Field(default_factory=list)
    llm_retrieval_notes: str | None = None
    degraded_mode: bool = False
    model_used: str | None = None


class DataRetrieverAgent:
    """Unified Data Retrieval Agent executing concurrent SQLite + ChromaDB I/O."""

    def __init__(
        self,
        ollama_base_url: str | None = None,
        model_name: str | None = None,
        account_history_skill: AccountHistorySkill | None = None,
        policy_retrieval_skill: PolicyRetrievalSkill | None = None,
        db_path: str | Path | None = None,
        enable_rag: bool | None = None,
    ) -> None:
        self.ollama_base_url = ollama_base_url or settings.ollama_base_url
        self.preferred_model = model_name or settings.data_retrieval_model
        self.model_name = self.preferred_model
        self.skill = account_history_skill or AccountHistorySkill()
        self.policy_skill = policy_retrieval_skill or PolicyRetrievalSkill()
        self.db_path = db_path
        self.enable_rag = settings.enable_rag_policy_retrieval if enable_rag is None else enable_rag

    def _get_resolved_model(self) -> str:
        """Resolve Tier 1 model against installed Ollama models with fallback."""
        return resolve_ollama_model(
            preferred_model=self.preferred_model,
            fallback_model=settings.ollama_model,
            base_url=self.ollama_base_url,
        )

    def _build_llm_with_skills(self) -> tuple[Any, str]:
        """Bind both SQLite AccountHistorySkill and ChromaDB PolicyRetrievalSkill tools to ChatOllama."""
        resolved_model = self._get_resolved_model()
        llm = ChatOllama(
            base_url=self.ollama_base_url,
            model=resolved_model,
            temperature=0.0,
        )
        bound_tools = [self.skill.get_langchain_tool()]
        if self.enable_rag:
            bound_tools.append(self.policy_skill.get_langchain_tool())
        return llm.bind_tools(bound_tools), resolved_model

    @safe_traceable(name="lookup_account_history", run_type="tool")
    async def _execute_account_history(
        self,
        account_id: str,
        db_path: str | Path | None = None,
    ) -> tuple[dict[str, Any], list[RiskFactor], str]:
        """Traced SQLite customer account history lookup."""
        return await self.skill.execute(account_id=account_id, db_path=db_path)

    @safe_traceable(name="PolicyRetrievalSkill", run_type="retriever")
    async def _execute_policy_retrieval(
        self,
        transaction: Transaction,
        policy_year: str,
        n_results: int = 3,
        category: str | None = None,
        custom_query: str | None = None,
    ) -> tuple[list[dict[str, Any]], str]:
        """Traced ChromaDB vector similarity search for fraud policy clauses."""
        return await self.policy_skill.execute(
            transaction=transaction,
            policy_year=policy_year,
            n_results=n_results,
            category=category,
            custom_query=custom_query,
        )

    @safe_traceable(name="DataRetrieverAgent.retrieve_data", run_type="chain")
    async def retrieve_data(
        self,
        transaction: Transaction,
        use_llm: bool = False,
        db_path: str | Path | None = None,
        policy_year: str | None = None,
        enable_rag: bool | None = None,
    ) -> DataRetrievalResult:
        """Concurrently retrieve SQLite customer profile & ChromaDB RAG policy clauses."""
        llm_notes: str | None = None
        tools_invoked: list[str] = []
        effective_db_path = db_path or self.db_path
        effective_year = policy_year or settings.default_policy_year
        should_use_rag = self.enable_rag if enable_rag is None else enable_rag
        resolved_model = self.preferred_model
        degraded_mode = False

        if use_llm:
            try:
                llm_with_tools, resolved_model = self._build_llm_with_skills()
                messages = [
                    SystemMessage(content=DATA_RETRIEVER_SYSTEM_PROMPT),
                    HumanMessage(
                        content=(
                            f"Retrieve account history for account_id='{transaction.account_id}' "
                            f"and fraud policy clauses (year={effective_year}) for "
                            f"transaction_id='{transaction.transaction_id}' "
                            f"(${transaction.amount:,.2f} {transaction.currency} at MCC {transaction.merchant.mcc})."
                        )
                    ),
                ]
                response = await llm_with_tools.ainvoke(messages)
                if getattr(response, "tool_calls", None):
                    for tc in response.tool_calls:
                        t_name = str(tc.get("name", ""))
                        if t_name and t_name not in tools_invoked:
                            tools_invoked.append(t_name)
                if response.content:
                    llm_notes = str(response.content)
            except Exception:
                llm_notes = None

        # Concurrent I/O execution across SQLite and ChromaDB via asyncio.gather()
        try:
            if should_use_rag:
                sql_task = self._execute_account_history(
                    account_id=transaction.account_id,
                    db_path=effective_db_path,
                )
                rag_task = self._execute_policy_retrieval(
                    transaction=transaction,
                    policy_year=effective_year,
                    n_results=3,
                )
                (
                    (account_history, risk_factors, sql_tool_name),
                    (rag_policies, rag_tool_name),
                ) = await asyncio.gather(
                    sql_task,
                    rag_task,
                )
                if sql_tool_name not in tools_invoked:
                    tools_invoked.append(sql_tool_name)
                if rag_tool_name not in tools_invoked:
                    tools_invoked.append(rag_tool_name)
            else:
                account_history, risk_factors, sql_tool_name = await self._execute_account_history(
                    account_id=transaction.account_id,
                    db_path=effective_db_path,
                )
                rag_policies = []
                if sql_tool_name not in tools_invoked:
                    tools_invoked.append(sql_tool_name)
        except Exception:
            degraded_mode = True
            account_history = {"account_id": transaction.account_id, "trust_tier": "unknown"}
            risk_factors = []
            rag_policies = []

        return DataRetrievalResult(
            account_id=transaction.account_id,
            account_history=account_history,
            rag_policies=rag_policies,
            risk_factors=risk_factors,
            tools_invoked=tools_invoked,
            llm_retrieval_notes=llm_notes,
            degraded_mode=degraded_mode,
            model_used=resolved_model,
        )

    @safe_traceable(name="DataRetrieverAgent.retrieve_supplementary_data", run_type="retriever")
    async def retrieve_supplementary_data(
        self,
        transaction: Transaction,
        supplementary_query: str,
        policy_year: str | None = None,
        category: str | None = None,
        db_path: str | Path | None = None,
    ) -> dict[str, Any]:
        """Handle an on-demand supplementary retrieval request from AnalysisAgent via the Supervisor."""
        effective_year = policy_year or settings.default_policy_year
        policies, tool_name = await self._execute_policy_retrieval(
            transaction=transaction,
            policy_year=effective_year,
            n_results=2,
            category=category,
            custom_query=supplementary_query,
        )
        return {
            "query": supplementary_query,
            "policy_year": effective_year,
            "category": category,
            "tool_invoked": tool_name,
            "retrieved_policies": policies,
        }
