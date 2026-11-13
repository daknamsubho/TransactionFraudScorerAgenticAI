"""Decision Agent (`src/fraud_scorer/agents/decision_agent.py`).

Implements the Actor in the Actor-Critic topology using Tier 3 Reasoning
(`llama3.1:8b` with automatic local Ollama fallback, PRD-019).
"""

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama

from fraud_scorer.agents.analysis_agent import AnalysisResult
from fraud_scorer.agents.data_retriever_agent import DataRetrievalResult
from fraud_scorer.config import resolve_ollama_model, settings
from fraud_scorer.models.transaction import FraudAssessment, RiskFactor, Transaction
from fraud_scorer.skills.risk_scoring_decision_skill import RiskScoringDecisionSkill

DECISION_AGENT_SYSTEM_PROMPT = """\
You are the Decision Agent (Actor — Tier 3 Reasoning LLM) in a financial fraud detection system.
You receive customer profile data, ChromaDB RAG policy clauses, and risk analysis factors from the Orchestrator Agent.
Your responsibility is to synthesize the final fraud risk rationale explaining the composite score (0.0-100.0)
and disposition:
- 0.0 to 29.9   -> APPROVE
- 30.0 to 69.9  -> REVIEW
- 70.0 to 100.0 -> DECLINE
If the Evaluator Agent (Critic) provides remediation feedback on a retry pass, you MUST address that feedback directly.
Keep your rationale concise (1-2 sentences) and grounded strictly in the provided evidence and policy clauses."""


class DecisionAgent:
    """LangChain Agent (Actor) that computes the risk score and APPROVE/REVIEW/DECLINE decision."""

    def __init__(
        self,
        ollama_base_url: str | None = None,
        model_name: str | None = None,
        decision_skill: RiskScoringDecisionSkill | None = None,
    ) -> None:
        self.ollama_base_url = ollama_base_url or settings.ollama_base_url
        self.preferred_model = model_name or settings.decision_model
        self.model_name = self.preferred_model
        self.decision_skill = decision_skill or RiskScoringDecisionSkill()

    def _get_resolved_model(self) -> str:
        """Resolve Tier 3 model (`llama3.1:8b`) against installed Ollama models with fallback."""
        return resolve_ollama_model(
            preferred_model=self.preferred_model,
            fallback_model=settings.ollama_model,
            base_url=self.ollama_base_url,
        )

    async def make_decision(
        self,
        transaction: Transaction,
        data_result: DataRetrievalResult | None = None,
        analysis_result: AnalysisResult | None = None,
        use_llm: bool = False,
        evaluator_feedback: str | None = None,
        supplementary_retrievals: list[dict[str, Any]] | None = None,
    ) -> FraudAssessment:
        """Ingest all relevant data from the Orchestrator and produce a draft or revised FraudAssessment."""
        aggregated_factors: list[RiskFactor] = []
        aggregated_tools: list[str] = []
        rag_policies: list[dict[str, Any]] = []

        if data_result is not None:
            aggregated_factors.extend(data_result.risk_factors)
            aggregated_tools.extend(data_result.tools_invoked)
            rag_policies.extend(data_result.rag_policies)

        if supplementary_retrievals:
            for item in supplementary_retrievals:
                t_inv = item.get("tool_invoked")
                if t_inv and t_inv not in aggregated_tools:
                    aggregated_tools.append(str(t_inv))
                for pol in item.get("retrieved_policies") or []:
                    rag_policies.append(pol)

        if analysis_result is not None:
            aggregated_factors.extend(analysis_result.risk_factors)
            aggregated_tools.extend(analysis_result.tools_invoked)

        llm_notes: str | None = None
        if use_llm:
            try:
                resolved_model = self._get_resolved_model()
                llm = ChatOllama(
                    base_url=self.ollama_base_url,
                    model=resolved_model,
                    temperature=0.0,
                )
                factors_desc = (
                    "; ".join(
                        f"{rf.category} (+{rf.contribution_score}): {rf.description}"
                        for rf in aggregated_factors
                    )
                    or "No elevated risk factors detected."
                )
                policies_desc = (
                    "; ".join(
                        f"[{p.get('clause_id', 'N/A')}] {p.get('title', '')}"
                        for p in rag_policies[:3]
                    )
                    or "Standard taxonomy rules."
                )
                critique_prompt = (
                    f" Evaluator remediation feedback to apply: {evaluator_feedback}."
                    if evaluator_feedback
                    else ""
                )
                messages = [
                    SystemMessage(content=DECISION_AGENT_SYSTEM_PROMPT),
                    HumanMessage(
                        content=(
                            f"Transaction {transaction.transaction_id} for account '{transaction.account_id}' "
                            f"(${transaction.amount:,.2f} {transaction.currency}). "
                            f"Account history: {data_result.account_history if data_result else {}}. "
                            f"Risk factors: {factors_desc}. "
                            f"Applicable RAG Policies: {policies_desc}.{critique_prompt} "
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
            rag_policies=rag_policies,
            evaluator_feedback=evaluator_feedback,
        )
