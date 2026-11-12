"""LangGraph State Machine Workflow (`src/fraud_scorer/agents/workflow.py`).

Implements the Hybrid Supervisor with Actor-Critic Feedback, Controlled Sub-Delegation,
and Dual-Plane Real-Time Step Streaming (PRD-017 & PRD-018) as specified in
`docs/agentic-architecture-pattern.md`.
"""

import contextvars
import inspect
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from fraud_scorer.agents.analysis_agent import AnalysisAgent, AnalysisResult
from fraud_scorer.agents.data_retriever_agent import DataRetrievalResult, DataRetrieverAgent
from fraud_scorer.agents.decision_agent import DecisionAgent
from fraud_scorer.agents.evaluator_agent import EvaluatorAgent
from fraud_scorer.config import AgentFeatureFlags, settings
from fraud_scorer.models.transaction import (
    AgentStepEvent,
    AgentStepEventType,
    FraudAssessment,
    RiskFactor,
    Transaction,
)
from fraud_scorer.observability.tracer import get_langsmith_trace_url, safe_traceable

logger = logging.getLogger(__name__)

StepEventCallback = Callable[[AgentStepEvent], Awaitable[None] | None]

_ACTIVE_STEP_CALLBACK: contextvars.ContextVar[StepEventCallback | None] = contextvars.ContextVar(
    "_ACTIVE_STEP_CALLBACK",
    default=None,
)


def set_step_event_callback(callback: StepEventCallback | None) -> contextvars.Token[StepEventCallback | None]:
    """Bind a per-request step event callback in the current async context."""
    return _ACTIVE_STEP_CALLBACK.set(callback)


def reset_step_event_callback(token: contextvars.Token[StepEventCallback | None]) -> None:
    """Restore the previous step event callback in the current async context."""
    _ACTIVE_STEP_CALLBACK.reset(token)


class FraudEvaluationState(BaseModel):
    """Explicit state schema maintained across the LangGraph Supervisor workflow."""

    # Ingress Data
    transaction_id: str
    transaction: dict[str, Any]
    policy_year: str = "2026"
    db_path: str | None = None
    use_llm: bool = False
    trace_id: str | None = None

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
    on_step_event: StepEventCallback | None = None,
) -> Any:
    """Build and compile the LangGraph StateGraph for the Hybrid Supervisor-Critic pattern."""

    async def _emit_step(
        state: FraudEvaluationState,
        event_type: AgentStepEventType,
        node_name: str,
        status: str,
        elapsed_ms: float,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Emit an AgentStepEvent to the active callback if WebSocket streaming is enabled."""
        if not settings.enable_websocket_trace_streaming:
            return
        cb = _ACTIVE_STEP_CALLBACK.get() or on_step_event
        if cb is None:
            return

        account_id = str(state.transaction.get("account_id", "")) or None
        event = AgentStepEvent(
            event_type=event_type.value,
            transaction_id=state.transaction_id,
            username=account_id,
            trace_id=state.trace_id,
            node_name=node_name,
            status=status,
            elapsed_ms=round(max(0.0, elapsed_ms), 2),
            retry_count=state.retry_count,
            message=message,
            details={
                "policy_year": state.policy_year,
                "is_fallback": state.is_fallback,
                "trace_url": get_langsmith_trace_url(state.trace_id),
                **(details or {}),
            },
        )
        try:
            res = cb(event)
            if inspect.isawaitable(res):
                await res
        except Exception as exc:
            logger.warning("Step event callback failed for node %s: %s", node_name, exc)

    @safe_traceable(name="DataRetrieverNode", run_type="chain")
    async def data_retrieval_node(state: FraudEvaluationState) -> dict[str, Any]:
        """Step 1: Retrieve baseline profile from SQLite & policy clauses from ChromaDB."""
        step_start = time.monotonic()
        await _emit_step(
            state=state,
            event_type=AgentStepEventType.STEP_STARTED,
            node_name="DataRetrieverAgent",
            status="STARTED",
            elapsed_ms=0.0,
            message="Retrieving customer account history & ChromaDB fraud policy clauses...",
        )

        if not agent_flags.enable_data_retriever_agent:
            await _emit_step(
                state=state,
                event_type=AgentStepEventType.STEP_COMPLETED,
                node_name="DataRetrieverAgent",
                status="SKIPPED",
                elapsed_ms=(time.monotonic() - step_start) * 1000.0,
                message="DataRetrieverAgent disabled via feature flag.",
            )
            return {"retrieval_data": None}

        tx = Transaction.model_validate(state.transaction)
        res = await data_retriever_agent.retrieve_data(
            transaction=tx,
            use_llm=state.use_llm,
            db_path=state.db_path,
            policy_year=state.policy_year,
            enable_rag=agent_flags.enable_rag_policy_retrieval,
        )
        elapsed = (time.monotonic() - step_start) * 1000.0

        await _emit_step(
            state=state,
            event_type=AgentStepEventType.TOOL_EXECUTED,
            node_name="DataRetrieverAgent",
            status="TOOLS_COMPLETED",
            elapsed_ms=elapsed,
            message=f"Executed tools: {', '.join(res.tools_invoked) or 'none'}",
            details={
                "tools_invoked": res.tools_invoked,
                "clauses_count": len(res.rag_policies),
                "trust_tier": res.account_history.get("trust_tier", "unknown"),
            },
        )
        await _emit_step(
            state=state,
            event_type=AgentStepEventType.STEP_COMPLETED,
            node_name="DataRetrieverAgent",
            status="COMPLETED",
            elapsed_ms=elapsed,
            message=(
                f"Fetched account profile & {len(res.rag_policies)} policy clause(s) "
                f"({elapsed:.0f}ms)"
            ),
            details={
                "tools_invoked": res.tools_invoked,
                "clauses_count": len(res.rag_policies),
                "model_used": res.model_used,
            },
        )
        return {"retrieval_data": res.model_dump(mode="json")}

    @safe_traceable(name="AnalysisNode", run_type="chain")
    async def analysis_node(state: FraudEvaluationState) -> dict[str, Any]:
        """Step 2: Compute multi-vector risk signals & check if supplementary data is needed."""
        step_start = time.monotonic()
        await _emit_step(
            state=state,
            event_type=AgentStepEventType.STEP_STARTED,
            node_name="AnalysisAgent",
            status="STARTED",
            elapsed_ms=0.0,
            message="Executing velocity, geographic haversine, merchant, and amount risk skills...",
        )

        if not agent_flags.enable_analysis_agent:
            await _emit_step(
                state=state,
                event_type=AgentStepEventType.STEP_COMPLETED,
                node_name="AnalysisAgent",
                status="SKIPPED",
                elapsed_ms=(time.monotonic() - step_start) * 1000.0,
                message="AnalysisAgent disabled via feature flag.",
            )
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

        elapsed = (time.monotonic() - step_start) * 1000.0
        await _emit_step(
            state=state,
            event_type=AgentStepEventType.TOOL_EXECUTED,
            node_name="AnalysisAgent",
            status="TOOLS_COMPLETED",
            elapsed_ms=elapsed,
            message=f"Executed analytical skills: {', '.join(res.tools_invoked) or 'none'}",
            details={
                "tools_invoked": res.tools_invoked,
                "risk_factors_count": len(combined_factors),
                "categories": [rf.get("category") for rf in combined_factors],
            },
        )
        await _emit_step(
            state=state,
            event_type=AgentStepEventType.STEP_COMPLETED,
            node_name="AnalysisAgent",
            status="COMPLETED",
            elapsed_ms=elapsed,
            message=(
                f"Calculated velocity burst & geo haversine distance — "
                f"{len(combined_factors)} risk signal(s) ({elapsed:.0f}ms)"
            ),
            details={
                "tools_invoked": res.tools_invoked,
                "risk_factors_count": len(combined_factors),
                "needs_supplementary_data": res.needs_supplementary_data,
                "model_used": res.model_used,
            },
        )

        return {
            "analysis_data": res.model_dump(mode="json"),
            "risk_factors": combined_factors,
            "analysis_completed": True,
            "needs_supplementary_data": res.needs_supplementary_data,
            "supplementary_query": res.supplementary_query,
            "supplementary_category": res.supplementary_category,
        }

    @safe_traceable(name="SupplementaryRetrievalNode", run_type="chain")
    async def supplementary_retrieval_node(state: FraudEvaluationState) -> dict[str, Any]:
        """On-Demand Deep Query routed by Supervisor from AnalysisAgent to DataRetrieverAgent."""
        step_start = time.monotonic()
        await _emit_step(
            state=state,
            event_type=AgentStepEventType.STEP_STARTED,
            node_name="SupplementaryRetriever",
            status="STARTED",
            elapsed_ms=0.0,
            message=f"Fetching supplementary policy data for query: '{state.supplementary_query}'...",
        )

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
        elapsed = (time.monotonic() - step_start) * 1000.0
        await _emit_step(
            state=state,
            event_type=AgentStepEventType.STEP_COMPLETED,
            node_name="SupplementaryRetriever",
            status="COMPLETED",
            elapsed_ms=elapsed,
            message=(
                f"Retrieved {len(supp_item.get('retrieved_policies', []))} supplementary policy clause(s) "
                f"({elapsed:.0f}ms)"
            ),
            details={"query": state.supplementary_query, "category": state.supplementary_category},
        )
        return {
            "supplementary_retrievals": updated_supps,
            "supplementary_count": state.supplementary_count + 1,
            "needs_supplementary_data": False,
        }

    @safe_traceable(name="DecisionNode", run_type="chain")
    async def decision_node(state: FraudEvaluationState) -> dict[str, Any]:
        """Step 3: Actor (DecisionAgent) synthesizes composite score, disposition, and rationale."""
        step_start = time.monotonic()
        await _emit_step(
            state=state,
            event_type=AgentStepEventType.STEP_STARTED,
            node_name="DecisionAgent",
            status="STARTED",
            elapsed_ms=0.0,
            message=(
                f"Synthesizing composite risk score & disposition "
                f"(pass #{state.retry_count + 1})..."
            ),
        )

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
                langsmith_run_id=state.trace_id,
                trace_url=get_langsmith_trace_url(state.trace_id),
            )
            elapsed = (time.monotonic() - step_start) * 1000.0
            await _emit_step(
                state=state,
                event_type=AgentStepEventType.STEP_COMPLETED,
                node_name="DecisionAgent",
                status="SKIPPED",
                elapsed_ms=elapsed,
                message="DecisionAgent disabled via feature flag (defaulted to APPROVE 0.0).",
                details={"score": 0.0, "decision": "APPROVE"},
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
        assessment.langsmith_run_id = state.trace_id
        assessment.trace_url = get_langsmith_trace_url(state.trace_id)

        elapsed = (time.monotonic() - step_start) * 1000.0
        await _emit_step(
            state=state,
            event_type=AgentStepEventType.STEP_COMPLETED,
            node_name="DecisionAgent",
            status="COMPLETED",
            elapsed_ms=elapsed,
            message=(
                f"Proposed score {assessment.overall_risk_score:.1f} "
                f"({assessment.decision}) ({elapsed:.0f}ms)"
            ),
            details={
                "score": assessment.overall_risk_score,
                "decision": assessment.decision,
                "assessment_id": assessment.assessment_id,
            },
        )
        return {
            "draft_assessment": assessment.model_dump(mode="json"),
            "draft_score": assessment.overall_risk_score,
            "draft_disposition": assessment.decision,
            "draft_reasoning": assessment.reasoning_summary,
        }

    @safe_traceable(name="EvaluatorNode", run_type="chain")
    async def evaluator_node(state: FraudEvaluationState) -> dict[str, Any]:
        """Step 4: Critic (EvaluatorAgent) audits the draft assessment for math & policy compliance."""
        step_start = time.monotonic()
        await _emit_step(
            state=state,
            event_type=AgentStepEventType.STEP_STARTED,
            node_name="EvaluatorAgent",
            status="STARTED",
            elapsed_ms=0.0,
            message="Auditing draft assessment for mathematical & policy compliance...",
        )

        if (
            not agent_flags.enable_evaluator_agent
            or not agent_flags.enable_decision_agent
            or state.draft_assessment is None
        ):
            elapsed = (time.monotonic() - step_start) * 1000.0
            await _emit_step(
                state=state,
                event_type=AgentStepEventType.CRITIC_VERDICT,
                node_name="EvaluatorAgent",
                status="ACCEPTED",
                elapsed_ms=elapsed,
                message="EvaluatorAgent audit bypassed (feature flag disabled) - ACCEPTED",
                details={"verdict": "ACCEPTED"},
            )
            await _emit_step(
                state=state,
                event_type=AgentStepEventType.STEP_COMPLETED,
                node_name="EvaluatorAgent",
                status="COMPLETED",
                elapsed_ms=elapsed,
                message=f"Evaluator check completed ({elapsed:.0f}ms)",
                details={"verdict": "ACCEPTED"},
            )
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
        elapsed = (time.monotonic() - step_start) * 1000.0

        await _emit_step(
            state=state,
            event_type=AgentStepEventType.CRITIC_VERDICT,
            node_name="EvaluatorAgent",
            status=verdict.verdict,
            elapsed_ms=elapsed,
            message=(
                f"Verified policy consistency - {verdict.verdict} ({elapsed:.0f}ms)"
                if verdict.verdict == "ACCEPTED"
                else (
                    f"Critic REJECTED draft ({verdict.rejection_category}): "
                    f"{verdict.remediation_instruction}"
                )
            ),
            details={
                "verdict": verdict.verdict,
                "rejection_category": verdict.rejection_category,
                "remediation_target": verdict.target_agent,
                "audit_notes": verdict.audit_notes,
            },
        )
        await _emit_step(
            state=state,
            event_type=AgentStepEventType.STEP_COMPLETED,
            node_name="EvaluatorAgent",
            status=verdict.verdict,
            elapsed_ms=elapsed,
            message=f"Evaluator audit verdict: {verdict.verdict} ({elapsed:.0f}ms)",
            details={"verdict": verdict.verdict},
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

    @safe_traceable(name="CircuitBreakerFallbackNode", run_type="chain")
    async def circuit_breaker_fallback_node(state: FraudEvaluationState) -> dict[str, Any]:
        """Circuit Breaker Fallback when retries > max_retries or SLA timeout is exceeded."""
        step_start = time.monotonic()
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
            langsmith_run_id=state.trace_id,
            trace_url=get_langsmith_trace_url(state.trace_id),
        )
        elapsed = (time.monotonic() - step_start) * 1000.0

        await _emit_step(
            state=state,
            event_type=AgentStepEventType.CIRCUIT_BREAKER_TRIGGERED,
            node_name="CircuitBreakerFallback",
            status="FALLBACK",
            elapsed_ms=elapsed,
            message=(
                f"Circuit Breaker Fallback triggered after {state.retry_count} retry pass(es) "
                f"-> {disposition} ({total_score:.1f})"
            ),
            details={
                "score": total_score,
                "decision": disposition,
                "retry_count": state.retry_count,
                "is_fallback": True,
            },
        )
        await _emit_step(
            state=state,
            event_type=AgentStepEventType.STEP_COMPLETED,
            node_name="CircuitBreakerFallback",
            status="COMPLETED",
            elapsed_ms=elapsed,
            message=f"Fallback assessment finalized: {disposition} ({total_score:.1f})",
            details={"score": total_score, "decision": disposition, "is_fallback": True},
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
