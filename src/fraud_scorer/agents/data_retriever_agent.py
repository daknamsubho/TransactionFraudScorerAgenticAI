"""Data Retriever Agent (`src/fraud_scorer/agents/data_retriever_agent.py`)."""

from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama
from pydantic import BaseModel, Field

from fraud_scorer.config import settings
from fraud_scorer.models.transaction import RiskFactor, Transaction
from fraud_scorer.skills.account_history_skill import AccountHistorySkill

DATA_RETRIEVER_SYSTEM_PROMPT = """You are the Data Retriever Agent in a multi-agent financial fraud detection system.
Your sole responsibility is to retrieve the customer's account history, profile age, prior disputes,
historical average spend, and trust tier using the `lookup_account_history_tool` skill.
Do NOT make any final fraud approval or decline decisions."""


class DataRetrievalResult(BaseModel):
    """Structured output returned by the Data Retriever Agent to the Orchestrator Agent."""

    account_id: str
    account_history: dict[str, Any] = Field(default_factory=dict)
    risk_factors: list[RiskFactor] = Field(default_factory=list)
    tools_invoked: list[str] = Field(default_factory=list)
    llm_retrieval_notes: str | None = None


class DataRetrieverAgent:
    """LangChain Agent responsible for fetching customer profile and account history via AccountHistorySkill."""

    def __init__(
        self,
        ollama_base_url: str | None = None,
        model_name: str | None = None,
        account_history_skill: AccountHistorySkill | None = None,
        db_path: str | Path | None = None,
    ) -> None:
        self.ollama_base_url = ollama_base_url or settings.ollama_base_url
        self.model_name = model_name or settings.ollama_model
        self.skill = account_history_skill or AccountHistorySkill()
        self.db_path = db_path

    def _build_llm_with_skill(self) -> Any:
        """Bind the AccountHistorySkill LangChain tool to ChatOllama."""
        llm = ChatOllama(
            base_url=self.ollama_base_url,
            model=self.model_name,
            temperature=0.0,
        )
        return llm.bind_tools([self.skill.get_langchain_tool()])

    async def retrieve_data(
        self,
        transaction: Transaction,
        use_llm: bool = False,
        db_path: str | Path | None = None,
    ) -> DataRetrievalResult:
        """Retrieve customer profile & historical metrics for a transaction."""
        llm_notes: str | None = None
        tools_invoked: list[str] = []
        effective_db_path = db_path or self.db_path

        if use_llm:
            try:
                llm_with_tools = self._build_llm_with_skill()
                messages = [
                    SystemMessage(content=DATA_RETRIEVER_SYSTEM_PROMPT),
                    HumanMessage(
                        content=(
                            f"Retrieve account history for account_id='{transaction.account_id}' "
                            f"on transaction_id='{transaction.transaction_id}'."
                        )
                    ),
                ]
                response = await llm_with_tools.ainvoke(messages)
                if getattr(response, "tool_calls", None):
                    for tc in response.tool_calls:
                        tools_invoked.append(str(tc.get("name", "lookup_account_history_tool")))
                if response.content:
                    llm_notes = str(response.content)
            except Exception:
                llm_notes = None

        account_history, risk_factors, tool_name = await self.skill.execute(
            account_id=transaction.account_id,
            db_path=effective_db_path,
        )
        if tool_name not in tools_invoked:
            tools_invoked.append(tool_name)

        return DataRetrievalResult(
            account_id=transaction.account_id,
            account_history=account_history,
            risk_factors=risk_factors,
            tools_invoked=tools_invoked,
            llm_retrieval_notes=llm_notes,
        )
