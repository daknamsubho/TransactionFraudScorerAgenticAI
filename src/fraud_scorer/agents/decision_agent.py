"""Decision Agent (`src/fraud_scorer/agents/decision_agent.py`)."""

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama

from fraud_scorer.agents.analysis_agent import AnalysisResult
from fraud_scorer.agents.data_retriever_agent import DataRetrievalResult
from fraud_scorer.config import settings
from fraud_scorer.models.transaction import FraudAssessment, RiskFactor, Transaction
from fraud_scorer.skills.risk_scoring_decision_skill import RiskScoringDecisionSkill

DECISION_AGENT_SYSTEM_PROMPT = """You are the Decision Agent in a multi-agent financial fraud detection system.
You receive all relevant customer profile data and risk analysis factors from the Orchestrator Agent.
Your responsibility is to synthesize the final fraud risk rationale explaining the composite score (0.0-100.0)
and disposition:
- 0.0 to 29.9  -> APPROVE
- 30.0 to 69.9 -> REVIEW
- 70.0 to 100.0 -> DECLINE
Keep your rationale concise (1-2 sentences) and grounded strictly in the provided evidence."""


class DecisionAgent:
    """LangChain Agent that computes the final risk score and APPROVE/REVIEW/DECLINE decision."""

    def __init__(
        self,
        ollama_base_url: str | None = None,
        model_name: str | None = None,
        decision_skill: RiskScoringDecisionSkill | None = None,
    ) -> None:
        self.ollama_base_url = ollama_base_url or settings.ollama_base_url
        self.model_name = model_name or settings.ollama_model
        self.decision_skill = decision_skill or RiskScoringDecisionSkill()

    async def make_decision(
        self,
        transaction: Transaction,
        data_result: DataRetrievalResult | None = None,
        analysis_result: AnalysisResult | None = None,
        use_llm: bool = False,
    ) -> FraudAssessment:
        """Ingest all relevant data from the Orchestrator and produce the final FraudAssessment."""
        aggregated_factors: list[RiskFactor] = []
        aggregated_tools: list[str] = []

        if data_result is not None:
            aggregated_factors.extend(data_result.risk_factors)
            aggregated_tools.extend(data_result.tools_invoked)

        if analysis_result is not None:
            aggregated_factors.extend(analysis_result.risk_factors)
            aggregated_tools.extend(analysis_result.tools_invoked)

        llm_notes: str | None = None
        if use_llm:
            try:
                llm = ChatOllama(
                    base_url=self.ollama_base_url,
                    model=self.model_name,
                    temperature=0.0,
                )
                factors_desc = (
                    "; ".join(
                        f"{rf.category} (+{rf.contribution_score}): {rf.description}"
                        for rf in aggregated_factors
                    )
                    or "No elevated risk factors detected."
                )
                messages = [
                    SystemMessage(content=DECISION_AGENT_SYSTEM_PROMPT),
                    HumanMessage(
                        content=(
                            f"Transaction {transaction.transaction_id} for account '{transaction.account_id}' "
                            f"(${transaction.amount:,.2f} {transaction.currency}). "
                            f"Account history: {data_result.account_history if data_result else {}}. "
                            f"Risk factors: {factors_desc}. "
                            "Provide a concise 1-sentence justification for the decision."
                        )
                    ),
                ]
                response = await llm.ainvoke(messages)
                if response.content:
                    llm_notes = str(response.content)
            except Exception:
                llm_notes = None

        return self.decision_skill.execute(
            transaction=transaction,
            risk_factors=aggregated_factors,
            tools_invoked=aggregated_tools,
            llm_reasoning_notes=llm_notes,
        )
