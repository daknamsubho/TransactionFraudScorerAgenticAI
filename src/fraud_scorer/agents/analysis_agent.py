"""Analysis Agent (`src/fraud_scorer/agents/analysis_agent.py`).

Implements the Tier 2 Analytical Agent (`llama3.1:8b`) with concurrent multi-vector
skill execution (`asyncio.gather`) and controlled sub-delegation (`request_supplementary_data`)
routed via the LangGraph Supervisor.
"""

import asyncio
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langchain_ollama import ChatOllama
from pydantic import BaseModel, Field

from fraud_scorer.config import resolve_ollama_model, settings
from fraud_scorer.models.transaction import RiskFactor, Transaction
from fraud_scorer.skills.amount_anomaly_skill import AmountAnomalySkill
from fraud_scorer.skills.geo_anomaly_skill import GeoAnomalySkill
from fraud_scorer.skills.merchant_risk_skill import MerchantRiskSkill
from fraud_scorer.skills.velocity_analysis_skill import VelocityAnalysisSkill

ANALYSIS_AGENT_SYSTEM_PROMPT = """You are the Analysis Agent (Tier 2 Analytical LLM) in a multi-agent financial fraud detection system.
Your responsibility is to invoke analytical skills (`check_velocity_tool`, `check_geo_anomaly_tool`,
and `check_merchant_risk_tool`) and identify fraud risk signals across velocity, geography, merchant category,
and transaction amount.
If initial retrieval data lacks policy grounding for a detected high-risk MCC or cross-border anomaly,
you may invoke `request_supplementary_data_tool` to request a secondary retrieval via the Supervisor.
Do NOT make the final APPROVE/REVIEW/DECLINE disposition — pass all findings to the Orchestrator
for the Decision Agent."""


@tool
def request_supplementary_data_tool(
    query: str,
    category: str | None = None,
) -> dict[str, Any]:
    """Request supplementary historical or policy data from DataRetrieverAgent via the Supervisor.

    Args:
        query: Specific question or scenario to retrieve from ChromaDB / SQLite.
        category: Optional policy category filter (e.g., 'MCC_RULES', 'GEOLOCATION', 'VELOCITY').
    """
    return {"requested_query": query, "category": category}


class AnalysisResult(BaseModel):
    """Structured output returned by the Analysis Agent to the Orchestrator Agent."""

    transaction_id: str
    velocity_data: dict[str, Any] = Field(default_factory=dict)
    geo_data: dict[str, Any] = Field(default_factory=dict)
    merchant_data: dict[str, Any] = Field(default_factory=dict)
    risk_factors: list[RiskFactor] = Field(default_factory=list)
    tools_invoked: list[str] = Field(default_factory=list)
    llm_analysis_notes: str | None = None
    needs_supplementary_data: bool = False
    supplementary_query: str | None = None
    supplementary_category: str | None = None
    model_used: str | None = None


class AnalysisAgent:
    """LangChain Agent responsible for multi-vector risk signal analysis via modular skills."""

    def __init__(
        self,
        ollama_base_url: str | None = None,
        model_name: str | None = None,
        velocity_skill: VelocityAnalysisSkill | None = None,
        geo_skill: GeoAnomalySkill | None = None,
        merchant_skill: MerchantRiskSkill | None = None,
        amount_skill: AmountAnomalySkill | None = None,
        db_path: str | Path | None = None,
    ) -> None:
        self.ollama_base_url = ollama_base_url or settings.ollama_base_url
        self.preferred_model = model_name or settings.analysis_model
        self.model_name = self.preferred_model
        self.velocity_skill = velocity_skill or VelocityAnalysisSkill()
        self.geo_skill = geo_skill or GeoAnomalySkill()
        self.merchant_skill = merchant_skill or MerchantRiskSkill()
        self.amount_skill = amount_skill or AmountAnomalySkill()
        self.db_path = db_path

    def _get_resolved_model(self) -> str:
        """Resolve Tier 2 model against installed Ollama models with fallback."""
        return resolve_ollama_model(
            preferred_model=self.preferred_model,
            fallback_model=settings.ollama_model,
            base_url=self.ollama_base_url,
        )

    def _build_llm_with_skills(self) -> tuple[Any, str]:
        """Bind analytical skill tools and supplementary data proxy tool to ChatOllama."""
        resolved_model = self._get_resolved_model()
        llm = ChatOllama(
            base_url=self.ollama_base_url,
            model=resolved_model,
            temperature=0.0,
        )
        return (
            llm.bind_tools(
                [
                    self.velocity_skill.get_langchain_tool(),
                    self.geo_skill.get_langchain_tool(),
                    self.merchant_skill.get_langchain_tool(),
                    request_supplementary_data_tool,
                ]
            ),
            resolved_model,
        )

    async def analyze_transaction(
        self,
        transaction: Transaction,
        account_history: dict[str, Any] | None = None,
        use_llm: bool = False,
        db_path: str | Path | None = None,
        rag_policies: list[dict[str, Any]] | None = None,
        supplementary_already_fetched: bool = False,
    ) -> AnalysisResult:
        """Concurrently execute velocity, geographic, merchant, and amount skills to synthesize RiskFactors."""
        llm_notes: str | None = None
        tools_invoked: list[str] = []
        effective_db_path = db_path or self.db_path
        resolved_model = self.preferred_model
        needs_supplementary = False
        supp_query: str | None = None
        supp_category: str | None = None

        if use_llm:
            try:
                llm_with_tools, resolved_model = self._build_llm_with_skills()
                messages = [
                    SystemMessage(content=ANALYSIS_AGENT_SYSTEM_PROMPT),
                    HumanMessage(
                        content=(
                            f"Analyze transaction {transaction.transaction_id} for account "
                            f"'{transaction.account_id}', amount=${transaction.amount:,.2f} "
                            f"{transaction.currency}, lat={transaction.location.latitude}, "
                            f"lon={transaction.location.longitude}, merchant_id='{transaction.merchant.merchant_id}', "
                            f"mcc='{transaction.merchant.mcc}'."
                        )
                    ),
                ]
                response = await llm_with_tools.ainvoke(messages)
                if getattr(response, "tool_calls", None):
                    for tc in response.tool_calls:
                        t_name = str(tc.get("name", ""))
                        if t_name:
                            tools_invoked.append(t_name)
                        if t_name == "request_supplementary_data_tool" and not supplementary_already_fetched:
                            args = tc.get("args") or {}
                            needs_supplementary = True
                            supp_query = str(args.get("query") or f"MCC {transaction.merchant.mcc} policy rules")
                            supp_category = args.get("category")
                if response.content:
                    llm_notes = str(response.content)
            except Exception:
                llm_notes = None

        # Execute the 3 async MCP analytical skills concurrently via asyncio.gather()
        (
            (v_data, v_factors, v_tool),
            (geo_data, geo_factors, geo_tool),
            (merch_data, merch_factors, merch_tool),
        ) = await asyncio.gather(
            self.velocity_skill.execute(
                account_id=transaction.account_id,
                window_minutes=60,
                db_path=effective_db_path,
            ),
            self.geo_skill.execute(
                account_id=transaction.account_id,
                current_lat=transaction.location.latitude,
                current_lon=transaction.location.longitude,
                current_timestamp_iso=transaction.timestamp.isoformat(),
                db_path=effective_db_path,
            ),
            self.merchant_skill.execute(
                merchant_id=transaction.merchant.merchant_id,
                mcc=transaction.merchant.mcc,
                db_path=effective_db_path,
            ),
        )

        # 4. Amount Anomaly Skill (in-memory calculation)
        amount_factors = self.amount_skill.execute(
            transaction=transaction,
            account_history=account_history,
        )

        for t_name in (v_tool, geo_tool, merch_tool):
            if t_name and t_name not in tools_invoked:
                tools_invoked.append(t_name)

        all_factors = [*v_factors, *geo_factors, *merch_factors, *amount_factors]

        # If high-risk signals are detected (e.g.,GEO_ANOMALY CRITICAL or MERCHANT_RISK) and
        # supplementary retrieval has not been performed yet and initial rag_policies is empty,
        # request targeted supplementary policy grounding from DataRetrieverAgent via Supervisor.
        if (
            not supplementary_already_fetched
            and not needs_supplementary
            and rag_policies is not None
            and len(rag_policies) == 0
            and any(rf.severity in ("HIGH", "CRITICAL") for rf in all_factors)
        ):
            needs_supplementary = True
            if geo_factors:
                supp_query = (
                    f"Impossible travel geo anomaly speed {geo_data.get('implied_speed_kmh', 900)} km/h "
                    f"in {transaction.location.country}"
                )
                supp_category = "GEOLOCATION"
            else:
                supp_query = f"High risk merchant MCC {transaction.merchant.mcc} amount ${transaction.amount:,.2f}"
                supp_category = "MCC_RULES"

        return AnalysisResult(
            transaction_id=transaction.transaction_id,
            velocity_data=v_data,
            geo_data=geo_data,
            merchant_data=merch_data,
            risk_factors=all_factors,
            tools_invoked=tools_invoked,
            llm_analysis_notes=llm_notes,
            needs_supplementary_data=needs_supplementary,
            supplementary_query=supp_query,
            supplementary_category=supp_category,
            model_used=resolved_model,
        )
