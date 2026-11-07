"""LangGraph State Machine Workflow (`src/fraud_scorer/agents/workflow.py`).

Implements the Hybrid Supervisor with Actor-Critic Feedback & Controlled Sub-Delegation
as specified in `docs/agentic-architecture-pattern.md`.
"""

import time
from typing import Any

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from fraud_scorer.agents.analysis_agent import AnalysisAgent, AnalysisResult
from fraud_scorer.agents.data_retriever_agent import DataRetrievalResult, DataRetrieverAgent
from fraud_scorer.agents.decision_agent import DecisionAgent
from fraud_scorer.agents.evaluator_agent import EvaluatorAgent
from fraud_scorer.config import AgentFeatureFlags
from fraud_scorer.models.transaction import FraudAssessment, RiskFactor, Transaction


class FraudEvaluationState(BaseModel):
    """Explicit state schema maintained across the LangGraph Supervisor workflow."""

    # Ingress Data
    transaction_id: str
    transaction: dict[str, Any]
    policy_year: str = "2026"
    db_path: str | None = None
    use_llm: bool = False

    # Enrichment State
    retrieval_data: dict[str, Any] | None = None
    supplementary_retrievals: list[dict[str, Any]] = Field(default_factory=list)
    supplementary_count: int = 0

    # Analysis State
    analysis_data: dict[str, Any] | None = None
    risk_factors: list[dict[str, Any]] = Field(default_factory=list)
    analysis_completed: bool = False
    needs_supplementary_data: bool = False
    supplementary_query: str | None = None
    supplementary_category: str | None = None

    # Decision State
    draft_assessment: dict[str, Any] | None = None
    draft_score: float | None = None
    draft_disposition: str | None = None
    draft_reasoning: str | None = None

    # Evaluator State
    evaluator_verdict: str | None = None  # "ACCEPTED" | "REJECTED"
    evaluator_feedback: str | None = None
    rejection_category: str | None = None
    remediation_target: str | None = None  # "analysis" | "decision"
    evaluator_audit_notes: str | None = None

    # Loop & SLA Circuit Breaker Controls
    retry_count: int = 0
    max_retries: int = 3
    max_timeout_ms: float = 1800.0
    is_fallback: bool = False
    execution_start_time: float = Field(default_factory=time.monotonic)


def build_fraud_evaluation_graph(
    data_retriever_agent: DataRetrieverAgent,
    analysis_agent: AnalysisAgent,
    decision_agent: DecisionAgent,
    evaluator_agent: EvaluatorAgent,
    agent_flags: AgentFeatureFlags,
) -> Any:
    """Build and compile the LangGraph StateGraph for the Hybrid Supervisor-Critic pattern."""

    async def data_retrieval_node(state: FraudEvaluationState) -> dict[str, Any]:
        """Step 1: Retrieve baseline profile from SQLite & policy clauses from ChromaDB."""
        if not agent_flags.enable_data_retriever_agent:
            return {"retrieval_data": None}

        tx = Transaction.model_validate(state.transaction)
        res = await data_retriever_agent.retrieve_data(
            transaction=tx,
            use_llm=state.use_llm,
            db_path=state.db_path,
            policy_year=state.policy_year,
            enable_rag=agent_flags.enable_rag_policy_retrieval,
        )
        return {"retrieval_data": res.model_dump(mode="json")}

    async def analysis_node(state: FraudEvaluationState) -> dict[str, Any]:
        """Step 2: Compute multi-vector risk signals & check if supplementary data is needed."""
        if not agent_flags.enable_analysis_agent:
            return {
                "analysis_data": None,
                "analysis_completed": True,
                "needs_supplementary_data": False,
            }

        tx = Transaction.model_validate(state.transaction)
        data_res = (
            DataRetrievalResult.model_validate(state.retrieval_data)
            if state.retrieval_data is not None
            else None
        )
        account_history = data_res.account_history if data_res is not None else None
        rag_policies = data_res.rag_policies if data_res is not None else None

        res = await analysis_agent.analyze_transaction(
            transaction=tx,
            account_history=account_history,
            use_llm=state.use_llm,
            db_path=state.db_path,
            rag_policies=rag_policies,
            supplementary_already_fetched=(state.supplementary_count >= 1),
        )

        combined_factors: list[dict[str, Any]] = []
        if data_res is not None:
            combined_factors.extend(rf.model_dump(mode="json") for rf in data_res.risk_factors)
        combined_factors.extend(rf.model_dump(mode="json") for rf in res.risk_factors)

        return {
            "analysis_data": res.model_dump(mode="json"),
            "risk_factors": combined_factors,
            "analysis_completed": True,
            "needs_supplementary_data": res.needs_supplementary_data,
            "supplementary_query": res.supplementary_query,
            "supplementary_category": res.supplementary_category,
        }

    async def supplementary_retrieval_node(state: FraudEvaluationState) -> dict[str, Any]:
        """On-Demand Deep Query routed by Supervisor from AnalysisAgent to DataRetrieverAgent."""
        if not agent_flags.enable_data_retriever_agent or not state.supplementary_query:
            return {
                "needs_supplementary_data": False,
                "supplementary_count": state.supplementary_count + 1,
            }

        tx = Transaction.model_validate(state.transaction)
        supp_item = await data_retriever_agent.retrieve_supplementary_data(
            transaction=tx,
            supplementary_query=state.supplementary_query,
            policy_year=state.policy_year,
            category=state.supplementary_category,
            db_path=state.db_path,
        )
        updated_supps = [*state.supplementary_retrievals, supp_item]
        return {
            "supplementary_retrievals": updated_supps,
            "supplementary_count": state.supplementary_count + 1,
            "needs_supplementary_data": False,
        }

    async def decision_node(state: FraudEvaluationState) -> dict[str, Any]:
        """Step 3: Actor (DecisionAgent) synthesizes composite score, disposition, and rationale."""
        tx = Transaction.model_validate(state.transaction)
        data_res = (
            DataRetrievalResult.model_validate(state.retrieval_data)
            if state.retrieval_data is not None
            else None
        )
        analysis_res = (
            AnalysisResult.model_validate(state.analysis_data)
            if state.analysis_data is not None
            else None
        )

        if not agent_flags.enable_decision_agent:
            invoked_tools: list[str] = []
            if data_res is not None:
                invoked_tools.extend(data_res.tools_invoked)
            if analysis_res is not None:
                invoked_tools.extend(analysis_res.tools_invoked)
            disabled_assessment = FraudAssessment(
                transaction_id=tx.transaction_id,
                account_id=tx.account_id,
                overall_risk_score=0.0,
                decision="APPROVE",
                risk_factors=[
                    *(data_res.risk_factors if data_res else []),
                    *(analysis_res.risk_factors if analysis_res else []),
                ],
                reasoning_summary=(
                    f"Decision Agent is disabled via feature flag "
                    f"(enable_decision_agent=False) for transaction {tx.transaction_id}."
                ),
                tools_invoked=list(dict.fromkeys(invoked_tools)),
            )
            return {
                "draft_assessment": disabled_assessment.model_dump(mode="json"),
                "draft_score": disabled_assessment.overall_risk_score,
                "draft_disposition": disabled_assessment.decision,
                "draft_reasoning": disabled_assessment.reasoning_summary,
            }

        assessment = await decision_agent.make_decision(
            transaction=tx,
            data_result=data_res,
            analysis_result=analysis_res,
            use_llm=state.use_llm,
            evaluator_feedback=state.evaluator_feedback,
            supplementary_retrievals=state.supplementary_retrievals,
        )
        return {
            "draft_assessment": assessment.model_dump(mode="json"),
            "draft_score": assessment.overall_risk_score,
            "draft_disposition": assessment.decision,
            "draft_reasoning": assessment.reasoning_summary,
        }

    async def evaluator_node(state: FraudEvaluationState) -> dict[str, Any]:
        """Step 4: Critic (EvaluatorAgent) audits the draft assessment for math & policy compliance."""
        if (
            not agent_flags.enable_evaluator_agent
            or not agent_flags.enable_decision_agent
            or state.draft_assessment is None
        ):
            return {
                "evaluator_verdict": "ACCEPTED",
                "evaluator_feedback": None,
                "remediation_target": None,
            }

        tx = Transaction.model_validate(state.transaction)
        draft = FraudAssessment.model_validate(state.draft_assessment)
        data_res = (
            DataRetrievalResult.model_validate(state.retrieval_data)
            if state.retrieval_data is not None
            else None
        )
        rag_policies = data_res.rag_policies if data_res is not None else None

        verdict = await evaluator_agent.evaluate_assessment(
            transaction=tx,
            draft_assessment=draft,
            rag_policies=rag_policies,
            use_llm=state.use_llm,
        )

        if verdict.verdict == "ACCEPTED":
            return {
                "evaluator_verdict": "ACCEPTED",
                "evaluator_feedback": None,
                "rejection_category": None,
                "remediation_target": None,
                "evaluator_audit_notes": verdict.audit_notes,
            }

        return {
            "evaluator_verdict": "REJECTED",
            "evaluator_feedback": verdict.remediation_instruction,
            "rejection_category": verdict.rejection_category,
            "remediation_target": verdict.target_agent or "decision",
            "evaluator_audit_notes": verdict.audit_notes,
            "retry_count": state.retry_count + 1,
        }

    async def circuit_breaker_fallback_node(state: FraudEvaluationState) -> dict[str, Any]:
        """Circuit Breaker Fallback when retries > max_retries or SLA timeout is exceeded."""
        tx = Transaction.model_validate(state.transaction)
        factors = [RiskFactor.model_validate(rf) for rf in state.risk_factors]
        total_score = min(round(sum(rf.contribution_score for rf in factors), 2), 100.0)
        has_critical_geo = any(
            rf.category == "GEO_ANOMALY" and rf.severity == "CRITICAL" for rf in factors
        )
        if has_critical_geo and total_score < 70.0:
            total_score = max(total_score, 75.0)

        # Per Section 2 & 6 of docs/agentic-architecture-pattern.md:
        # Force DECLINE if >= 70.0, else safe REVIEW fallback for human analyst queue.
        disposition = "DECLINE" if total_score >= 70.0 else "REVIEW"

        existing_tools: list[str] = []
        if state.draft_assessment and state.draft_assessment.get("tools_invoked"):
            existing_tools = list(state.draft_assessment["tools_invoked"])

        fallback_assessment = FraudAssessment(
            transaction_id=tx.transaction_id,
            account_id=tx.account_id,
            overall_risk_score=total_score,
            decision=disposition,
            risk_factors=factors,
            reasoning_summary=(
                f"Decision: {disposition} (Composite Score: {total_score}/100). "
                f"[Circuit Breaker Fallback triggered after {state.retry_count} retry pass(es): "
                f"{state.evaluator_feedback or 'SLA timeout exceeded'}]"
            ),
            tools_invoked=existing_tools,
        )
        return {
            "is_fallback": True,
            "draft_assessment": fallback_assessment.model_dump(mode="json"),
            "draft_score": fallback_assessment.overall_risk_score,
            "draft_disposition": fallback_assessment.decision,
            "draft_reasoning": fallback_assessment.reasoning_summary,
        }

    def route_after_analysis(state: FraudEvaluationState) -> str:
        """Route to SupplementaryRetrievalNode if AnalysisAgent requested deeper data (capped at 1)."""
        if (
            state.needs_supplementary_data
            and state.supplementary_count < 1
            and agent_flags.enable_data_retriever_agent
        ):
            return "supplementary_retrieval_node"
        return "decision_node"

    def route_after_evaluator(state: FraudEvaluationState) -> str:
        """Route based on EvaluatorAgent verdict, retry_count <= max_retries, and SLA timeout."""
        if state.evaluator_verdict == "ACCEPTED":
            return str(END)

        elapsed_ms = (time.monotonic() - state.execution_start_time) * 1000.0
        if state.retry_count <= state.max_retries and elapsed_ms < state.max_timeout_ms:
            if state.remediation_target == "analysis" and agent_flags.enable_analysis_agent:
                return "analysis_node"
            return "decision_node"

        return "circuit_breaker_fallback_node"

    graph = StateGraph(FraudEvaluationState)
    graph.add_node("data_retrieval_node", data_retrieval_node)
    graph.add_node("analysis_node", analysis_node)
    graph.add_node("supplementary_retrieval_node", supplementary_retrieval_node)
    graph.add_node("decision_node", decision_node)
    graph.add_node("evaluator_node", evaluator_node)
    graph.add_node("circuit_breaker_fallback_node", circuit_breaker_fallback_node)

    graph.add_edge(START, "data_retrieval_node")
    graph.add_edge("data_retrieval_node", "analysis_node")
    graph.add_conditional_edges(
        "analysis_node",
        route_after_analysis,
        {
            "supplementary_retrieval_node": "supplementary_retrieval_node",
            "decision_node": "decision_node",
        },
    )
    graph.add_edge("supplementary_retrieval_node", "analysis_node")
    graph.add_edge("decision_node", "evaluator_node")
    graph.add_conditional_edges(
        "evaluator_node",
        route_after_evaluator,
        {
            str(END): END,
            "decision_node": "decision_node",
            "analysis_node": "analysis_node",
            "circuit_breaker_fallback_node": "circuit_breaker_fallback_node",
        },
    )
    graph.add_edge("circuit_breaker_fallback_node", END)

    return graph.compile()
