"""Orchestrator Agent (`src/fraud_scorer/agents/orchestrator_agent.py`).

Implements the LangGraph Supervisor Orchestration Control Plane per `docs/agentic-architecture-pattern.md`
(PRD-013, PRD-017 & PRD-018):
- Pure supervisor driving a compiled LangGraph `StateGraph(FraudEvaluationState)`.
- Coordinates `DataRetrieverAgent` (Tier 1: `llama3.2:3b`), `AnalysisAgent` (Tier 2: `llama3.1:8b`),
  `DecisionAgent` (Actor — Tier 3: `qwen3.8:27b`), and `EvaluatorAgent` (Critic — Tier 3+: `qwen3.8:27b`).
- Mediates on-demand supplementary retrieval requests from `AnalysisAgent` to `DataRetrieverAgent`.
- Enforces Actor-Critic feedback loop (up to `max_retries=3`) and SLA circuit breaker (`1800ms`).
- Propagates LangSmith distributed trace context (`run_id`, tags, sanitized metadata) and streams
  live `AgentStepEvent` callbacks.
"""

import asyncio
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from fraud_scorer.agents.analysis_agent import AnalysisAgent
from fraud_scorer.agents.data_retriever_agent import DataRetrieverAgent
from fraud_scorer.agents.decision_agent import DecisionAgent
from fraud_scorer.agents.evaluator_agent import EvaluatorAgent
from fraud_scorer.agents.workflow import (
    FraudEvaluationState,
    StepEventCallback,
    build_fraud_evaluation_graph,
    reset_step_event_callback,
    set_step_event_callback,
)
from fraud_scorer.config import AgentFeatureFlags, AgentModelConfig, settings
from fraud_scorer.models.transaction import (
    FraudAssessment,
    GeoLocation,
    MerchantInfo,
    PaymentMethod,
    Transaction,
)
from fraud_scorer.observability.sanitizer import sanitize_transaction_payload
from fraud_scorer.observability.tracer import (
    build_langchain_run_config,
    get_langsmith_trace_url,
)

console = Console()


def check_ollama_connection(base_url: str | None = None) -> bool:
    """Check whether the local Ollama server is reachable."""
    url = base_url or settings.ollama_base_url
    try:
        resp = httpx.get(f"{url}/api/version", timeout=1.5)
        return resp.status_code == 200
    except Exception:
        return False


def is_ollama_available(base_url: str | None = None) -> bool:
    """Alias for check_ollama_connection to verify local Ollama server availability."""
    return check_ollama_connection(base_url)


class OrchestratorAgent:
    """LangGraph Supervisor Agent coordinating Data Retriever, Analysis, Decision (Actor), and Evaluator (Critic)."""

    def __init__(
        self,
        ollama_base_url: str | None = None,
        model_name: str | None = None,
        provider: str | None = None,
        agent_flags: AgentFeatureFlags | None = None,
        model_config: AgentModelConfig | None = None,
        data_retriever_agent: DataRetrieverAgent | None = None,
        analysis_agent: AnalysisAgent | None = None,
        decision_agent: DecisionAgent | None = None,
        evaluator_agent: EvaluatorAgent | None = None,
        db_path: str | Path | None = None,
        policy_year: str | None = None,
        max_retries: int | None = None,
        max_timeout_ms: float | None = None,
        on_step_event: StepEventCallback | None = None,
    ) -> None:
        self.ollama_base_url = ollama_base_url or settings.ollama_base_url
        self.model_name = model_name or settings.ollama_model
        self.provider = provider or settings.default_llm_provider
        self.agent_flags = agent_flags or settings.get_agent_flags()
        self.model_config_tiers = model_config or settings.get_model_config()
        self.db_path = db_path
        self.policy_year = policy_year or settings.default_policy_year
        self.max_retries = settings.max_evaluation_retries if max_retries is None else max_retries
        self.max_timeout_ms = (
            settings.max_evaluation_timeout_ms if max_timeout_ms is None else max_timeout_ms
        )
        self.on_step_event = on_step_event

        self.data_retriever_agent = data_retriever_agent or DataRetrieverAgent(
            ollama_base_url=self.ollama_base_url,
            model_name=model_name or self.model_config_tiers.data_retrieval_model,
            db_path=self.db_path,
            enable_rag=self.agent_flags.enable_rag_policy_retrieval,
        )
        self.analysis_agent = analysis_agent or AnalysisAgent(
            ollama_base_url=self.ollama_base_url,
            model_name=model_name or self.model_config_tiers.analysis_model,
            db_path=self.db_path,
        )
        self.decision_agent = decision_agent or DecisionAgent(
            ollama_base_url=self.ollama_base_url,
            model_name=model_name or self.model_config_tiers.decision_model,
        )
        self.evaluator_agent = evaluator_agent or EvaluatorAgent(
            ollama_base_url=self.ollama_base_url,
            model_name=model_name or self.model_config_tiers.evaluator_model,
        )

        self.workflow = build_fraud_evaluation_graph(
            data_retriever_agent=self.data_retriever_agent,
            analysis_agent=self.analysis_agent,
            decision_agent=self.decision_agent,
            evaluator_agent=self.evaluator_agent,
            agent_flags=self.agent_flags,
            on_step_event=self.on_step_event,
        )

    async def run_workflow_state(
        self,
        transaction: Transaction,
        db_path: str | Path | None = None,
        policy_year: str | None = None,
        on_step_event: StepEventCallback | None = None,
    ) -> FraudEvaluationState:
        """Execute the compiled LangGraph StateGraph and return the final FraudEvaluationState."""
        effective_db_path = str(db_path or self.db_path) if (db_path or self.db_path) else None
        effective_year = policy_year or self.policy_year
        use_llm = self.provider == "ollama" and check_ollama_connection(self.ollama_base_url)

        tx_dump = transaction.model_dump(mode="json")
        sanitized_tx = sanitize_transaction_payload(tx_dump) if settings.langsmith_mask_pii else tx_dump

        run_config = build_langchain_run_config(
            tx_id=transaction.transaction_id,
            account_id=transaction.account_id,
            policy_year=effective_year,
            tags=[
                f"mcc:{transaction.merchant.mcc}",
                f"rail:{transaction.payment_method.payment_type}",
            ],
            metadata={
                "amount": transaction.amount,
                "currency": transaction.currency,
                "merchant_category_code": transaction.merchant.mcc,
                "payment_type": transaction.payment_method.payment_type,
                "country": transaction.location.country,
                "sanitized_transaction": sanitized_tx,
                "max_retries": self.max_retries,
                "use_llm": use_llm,
            },
        )
        run_id_str = str(run_config["run_id"])

        initial_state = FraudEvaluationState(
            transaction_id=transaction.transaction_id,
            transaction=tx_dump,
            policy_year=effective_year,
            db_path=effective_db_path,
            use_llm=use_llm,
            trace_id=run_id_str,
            max_retries=self.max_retries,
            max_timeout_ms=self.max_timeout_ms,
            execution_start_time=time.monotonic(),
        )

        active_cb = on_step_event or self.on_step_event
        token = set_step_event_callback(active_cb)
        try:
            raw_final_state = await self.workflow.ainvoke(initial_state, config=run_config)
        finally:
            reset_step_event_callback(token)

        final_state = (
            raw_final_state
            if isinstance(raw_final_state, FraudEvaluationState)
            else FraudEvaluationState.model_validate(raw_final_state)
        )
        final_state.trace_id = run_id_str
        if final_state.draft_assessment is not None:
            final_state.draft_assessment["langsmith_run_id"] = run_id_str
            final_state.draft_assessment["trace_url"] = get_langsmith_trace_url(run_id_str)
        return final_state

    async def coordinate_evaluation(
        self,
        transaction: Transaction,
        db_path: str | Path | None = None,
        policy_year: str | None = None,
        on_step_event: StepEventCallback | None = None,
    ) -> FraudAssessment:
        """Coordinate sub-agents via LangGraph StateGraph and return the final FraudAssessment.

        Note: The Orchestrator Agent performs zero scoring or decisioning logic itself.
        """
        if not self.agent_flags.enable_orchestrator_agent:
            disabled_run_id = str(uuid4())
            return FraudAssessment(
                transaction_id=transaction.transaction_id,
                account_id=transaction.account_id,
                overall_risk_score=0.0,
                decision="APPROVE",
                risk_factors=[],
                reasoning_summary=(
                    f"Orchestrator Agent is disabled via feature flag "
                    f"(enable_orchestrator_agent=False) for transaction {transaction.transaction_id}."
                ),
                tools_invoked=[],
                langsmith_run_id=disabled_run_id,
                trace_url=get_langsmith_trace_url(disabled_run_id),
            )

        final_state = await self.run_workflow_state(
            transaction=transaction,
            db_path=db_path,
            policy_year=policy_year,
            on_step_event=on_step_event,
        )
        if final_state.draft_assessment is None:
            return FraudAssessment(
                transaction_id=transaction.transaction_id,
                account_id=transaction.account_id,
                overall_risk_score=0.0,
                decision="APPROVE",
                risk_factors=[],
                reasoning_summary="No assessment generated by workflow.",
                tools_invoked=[],
                langsmith_run_id=final_state.trace_id,
                trace_url=get_langsmith_trace_url(final_state.trace_id),
            )
        assessment = FraudAssessment.model_validate(final_state.draft_assessment)
        assessment.langsmith_run_id = final_state.trace_id
        assessment.trace_url = get_langsmith_trace_url(final_state.trace_id)
        return assessment

    async def evaluate_transaction(
        self,
        transaction: Transaction,
        db_path: str | Path | None = None,
        policy_year: str | None = None,
        on_step_event: StepEventCallback | None = None,
    ) -> FraudAssessment:
        """Evaluate a transaction by executing the LangGraph Supervisor-Critic workflow."""
        return await self.coordinate_evaluation(
            transaction=transaction,
            db_path=db_path,
            policy_year=policy_year,
            on_step_event=on_step_event,
        )


# Alias for backward compatibility across API Gateway and callers
FraudScorerOrchestrator = OrchestratorAgent


def display_assessment(tx: Transaction, assessment: FraudAssessment) -> None:
    """Pretty-print a FraudAssessment using Rich console formatting."""
    color = {"APPROVE": "green", "REVIEW": "yellow", "DECLINE": "red"}[assessment.decision]

    table = Table(title=f"Risk Factors for {tx.transaction_id}", show_header=True)
    table.add_column("Factor", style="cyan")
    table.add_column("Category", style="magenta")
    table.add_column("Severity", style="bold")
    table.add_column("Score (+)", justify="right")
    table.add_column("Evidence")

    if not assessment.risk_factors:
        table.add_row("None", "-", "LOW", "0.0", "No anomalous signals detected.")
    else:
        for rf in assessment.risk_factors:
            table.add_row(
                rf.category,
                rf.category,
                rf.severity,
                f"{rf.contribution_score:.1f}",
                rf.description,
            )

    summary_text = (
        f"[bold]Account ID:[/bold] {tx.account_id}\n"
        f"[bold]Amount:[/bold] ${tx.amount:,.2f} {tx.currency}\n"
        f"[bold]Merchant:[/bold] {tx.merchant.name} (MCC {tx.merchant.mcc})\n"
        f"[bold]Location:[/bold] {tx.location.city or 'Unknown'} "
        f"({tx.location.latitude}, {tx.location.longitude})\n"
        f"[bold]Overall Risk Score:[/bold] [{color}]{assessment.overall_risk_score:.1f} / 100.0[/{color}]\n"
        f"[bold]Decision:[/bold] [bold {color}]{assessment.decision}[/bold {color}]\n"
        f"[bold]Tools Invoked:[/bold] {', '.join(assessment.tools_invoked)}\n"
        f"[bold]LangSmith Run ID:[/bold] {assessment.langsmith_run_id or 'N/A'}\n\n"
        f"[italic]{assessment.reasoning_summary}[/italic]"
    )

    console.print(
        Panel(summary_text, title="Fraud Scorer Assessment (LangGraph Supervisor-Critic)", border_style=color)
    )
    console.print(table)
    console.print()


async def _async_demo() -> None:
    """Run sample normal and fraudulent transactions through the LangGraph multi-agent orchestrator."""
    orchestrator = OrchestratorAgent()
    ollama_up = is_ollama_available(orchestrator.ollama_base_url)

    tiers_info = (
        f"Tier 1={orchestrator.model_config_tiers.data_retrieval_model}, "
        f"Tier 2={orchestrator.model_config_tiers.analysis_model}, "
        f"Tier 3={orchestrator.model_config_tiers.decision_model}"
    )
    mode_str = (
        f"LangGraph + Ollama ({tiers_info} @ {orchestrator.ollama_base_url})"
        if ollama_up
        else f"LangGraph Multi-Agent Skill Mode ({tiers_info}; Ollama offline)"
    )
    console.print(Panel(f"[bold blue]Running in:[/bold blue] {mode_str}"))

    tx_legit = Transaction(
        transaction_id="tx_legit_001",
        account_id="acc_normal_01",
        amount=42.50,
        currency="USD",
        timestamp=datetime.now(UTC),
        location=GeoLocation(
            latitude=37.7749,
            longitude=-122.4194,
            city="San Francisco",
            country="US",
        ),
        payment_method=PaymentMethod(
            payment_type="credit_card",
            card_last_four="4242",
            is_card_present=True,
        ),
        merchant=MerchantInfo(
            merchant_id="merch_cafe_88",
            name="Blue Bottle Coffee",
            mcc="5499",
            country="US",
        ),
    )

    tx_fraud = Transaction(
        transaction_id="tx_fraud_999",
        account_id="acc_suspicious_01",
        amount=3500.00,
        currency="USD",
        timestamp=datetime.now(UTC),
        location=GeoLocation(
            latitude=35.6762,
            longitude=139.6503,
            city="Tokyo",
            country="JP",
        ),
        payment_method=PaymentMethod(
            payment_type="credit_card",
            card_last_four="9911",
            is_card_present=False,
        ),
        merchant=MerchantInfo(
            merchant_id="merch_casino_77",
            name="Tokyo High Roller Casino",
            mcc="7995",
            country="JP",
        ),
    )

    for tx in (tx_legit, tx_fraud):
        assessment = await orchestrator.evaluate_transaction(tx)
        display_assessment(tx, assessment)


def run_demo() -> None:
    """CLI entrypoint to run the transaction fraud scoring demo."""
    asyncio.run(_async_demo())


def main() -> None:
    """Script entrypoint for `fraud-scorer-agent`."""
    run_demo()


if __name__ == "__main__":
    main()
