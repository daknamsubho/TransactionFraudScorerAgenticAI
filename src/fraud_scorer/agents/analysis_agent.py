"""Analysis Agent (`src/fraud_scorer/agents/analysis_agent.py`)."""

from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama
from pydantic import BaseModel, Field

from fraud_scorer.config import settings
from fraud_scorer.models.transaction import RiskFactor, Transaction
from fraud_scorer.skills.amount_anomaly_skill import AmountAnomalySkill
from fraud_scorer.skills.geo_anomaly_skill import GeoAnomalySkill
from fraud_scorer.skills.merchant_risk_skill import MerchantRiskSkill
from fraud_scorer.skills.velocity_analysis_skill import VelocityAnalysisSkill

ANALYSIS_AGENT_SYSTEM_PROMPT = """You are the Analysis Agent in a multi-agent financial fraud detection system.
Your responsibility is to invoke analytical skills (`check_velocity_tool`, `check_geo_anomaly_tool`,
and `check_merchant_risk_tool`) and identify fraud risk signals across velocity, geography, merchant category,
and transaction amount.
Do NOT make the final APPROVE/REVIEW/DECLINE disposition — pass all findings to the Orchestrator
for the Decision Agent."""


class AnalysisResult(BaseModel):
    """Structured output returned by the Analysis Agent to the Orchestrator Agent."""

    transaction_id: str
    velocity_data: dict[str, Any] = Field(default_factory=dict)
    geo_data: dict[str, Any] = Field(default_factory=dict)
    merchant_data: dict[str, Any] = Field(default_factory=dict)
    risk_factors: list[RiskFactor] = Field(default_factory=list)
    tools_invoked: list[str] = Field(default_factory=list)
    llm_analysis_notes: str | None = None


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
        self.model_name = model_name or settings.ollama_model
        self.velocity_skill = velocity_skill or VelocityAnalysisSkill()
        self.geo_skill = geo_skill or GeoAnomalySkill()
        self.merchant_skill = merchant_skill or MerchantRiskSkill()
        self.amount_skill = amount_skill or AmountAnomalySkill()
        self.db_path = db_path

    def _build_llm_with_skills(self) -> Any:
        """Bind analytical skill tools to ChatOllama."""
        llm = ChatOllama(
            base_url=self.ollama_base_url,
            model=self.model_name,
            temperature=0.0,
        )
        return llm.bind_tools(
            [
                self.velocity_skill.get_langchain_tool(),
                self.geo_skill.get_langchain_tool(),
                self.merchant_skill.get_langchain_tool(),
            ]
        )

    async def analyze_transaction(
        self,
        transaction: Transaction,
        account_history: dict[str, Any] | None = None,
        use_llm: bool = False,
        db_path: str | Path | None = None,
    ) -> AnalysisResult:
        """Execute velocity, geographic, merchant, and amount skills to synthesize RiskFactors."""
        llm_notes: str | None = None
        tools_invoked: list[str] = []
        effective_db_path = db_path or self.db_path

        if use_llm:
            try:
                llm_with_tools = self._build_llm_with_skills()
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
                        tools_invoked.append(str(tc.get("name", "")))
                if response.content:
                    llm_notes = str(response.content)
            except Exception:
                llm_notes = None

        # 1. Velocity Analysis Skill
        v_data, v_factors, v_tool = await self.velocity_skill.execute(
            account_id=transaction.account_id,
            window_minutes=60,
            db_path=effective_db_path,
        )
        # 2. Geo Anomaly Skill
        geo_data, geo_factors, geo_tool = await self.geo_skill.execute(
            account_id=transaction.account_id,
            current_lat=transaction.location.latitude,
            current_lon=transaction.location.longitude,
            current_timestamp_iso=transaction.timestamp.isoformat(),
            db_path=effective_db_path,
        )
        # 3. Merchant Risk Skill
        merch_data, merch_factors, merch_tool = await self.merchant_skill.execute(
            merchant_id=transaction.merchant.merchant_id,
            mcc=transaction.merchant.mcc,
            db_path=effective_db_path,
        )
        # 4. Amount Anomaly Skill
        amount_factors = self.amount_skill.execute(
            transaction=transaction,
            account_history=account_history,
        )

        for t_name in (v_tool, geo_tool, merch_tool):
            if t_name and t_name not in tools_invoked:
                tools_invoked.append(t_name)

        all_factors = [*v_factors, *geo_factors, *merch_factors, *amount_factors]

        return AnalysisResult(
            transaction_id=transaction.transaction_id,
            velocity_data=v_data,
            geo_data=geo_data,
            merchant_data=merch_data,
            risk_factors=all_factors,
            tools_invoked=tools_invoked,
            llm_analysis_notes=llm_notes,
        )
