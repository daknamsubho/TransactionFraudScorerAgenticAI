"""Orchestrator Agent (`src/fraud_scorer/agents/orchestrator_agent.py`).

Per PRD-009:
- The Orchestrator Agent is strictly a manager/coordinator agent.
- It does NOT take any scoring or approval decision itself.
- It coordinates enabled sub-agents (`DataRetrieverAgent`, `AnalysisAgent`) according to
  configurable `AgentFeatureFlags` and provides all relevant data to the `DecisionAgent`,
  which returns the score and decision (`FraudAssessment`) back to the API Gateway.
"""

import asyncio
from datetime import UTC, datetime

import httpx
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from fraud_scorer.agents.analysis_agent import AnalysisAgent, AnalysisResult
from fraud_scorer.agents.data_retriever_agent import DataRetrievalResult, DataRetrieverAgent
from fraud_scorer.agents.decision_agent import DecisionAgent
from fraud_scorer.config import AgentFeatureFlags, settings
from fraud_scorer.models.transaction import (
    FraudAssessment,
    GeoLocation,
    MerchantInfo,
    PaymentMethod,
    Transaction,
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
    """Pure manager agent that coordinates Data Retriever, Analysis, and Decision agents."""

    def __init__(
        self,
        ollama_base_url: str | None = None,
        model_name: str | None = None,
        provider: str | None = None,
        agent_flags: AgentFeatureFlags | None = None,
        data_retriever_agent: DataRetrieverAgent | None = None,
        analysis_agent: AnalysisAgent | None = None,
        decision_agent: DecisionAgent | None = None,
    ) -> None:
        self.ollama_base_url = ollama_base_url or settings.ollama_base_url
        self.model_name = model_name or settings.ollama_model
        self.provider = provider or settings.default_llm_provider
        self.agent_flags = agent_flags or settings.get_agent_flags()

        self.data_retriever_agent = data_retriever_agent or DataRetrieverAgent(
            ollama_base_url=self.ollama_base_url,
            model_name=self.model_name,
        )
        self.analysis_agent = analysis_agent or AnalysisAgent(
            ollama_base_url=self.ollama_base_url,
            model_name=self.model_name,
        )
        self.decision_agent = decision_agent or DecisionAgent(
            ollama_base_url=self.ollama_base_url,
            model_name=self.model_name,
        )

    async def coordinate_evaluation(self, transaction: Transaction) -> FraudAssessment:
        """Coordinate enabled sub-agents and delegate the final decision to the Decision Agent.

        Note: The Orchestrator Agent performs zero scoring or decisioning logic itself.
        """
        if not self.agent_flags.enable_orchestrator_agent:
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
            )

        use_llm = self.provider == "ollama" and check_ollama_connection(self.ollama_base_url)

        # Step 1: Delegate data retrieval to DataRetrieverAgent (if enabled)
        data_result: DataRetrievalResult | None = None
        if self.agent_flags.enable_data_retriever_agent:
            data_result = await self.data_retriever_agent.retrieve_data(
                transaction=transaction,
                use_llm=use_llm,
            )

        # Step 2: Delegate multi-vector signal analysis to AnalysisAgent (if enabled)
        analysis_result: AnalysisResult | None = None
        if self.agent_flags.enable_analysis_agent:
            account_history = data_result.account_history if data_result is not None else None
            analysis_result = await self.analysis_agent.analyze_transaction(
                transaction=transaction,
                account_history=account_history,
                use_llm=use_llm,
            )

        # Step 3: Pass all gathered data to DecisionAgent (if enabled)
        if not self.agent_flags.enable_decision_agent:
            invoked_tools: list[str] = []
            if data_result is not None:
                invoked_tools.extend(data_result.tools_invoked)
            if analysis_result is not None:
                invoked_tools.extend(analysis_result.tools_invoked)
            return FraudAssessment(
                transaction_id=transaction.transaction_id,
                account_id=transaction.account_id,
                overall_risk_score=0.0,
                decision="APPROVE",
                risk_factors=[
                    *(data_result.risk_factors if data_result else []),
                    *(analysis_result.risk_factors if analysis_result else []),
                ],
                reasoning_summary=(
                    f"Decision Agent is disabled via feature flag "
                    f"(enable_decision_agent=False) for transaction {transaction.transaction_id}."
                ),
                tools_invoked=list(dict.fromkeys(invoked_tools)),
            )

        return await self.decision_agent.make_decision(
            transaction=transaction,
            data_result=data_result,
            analysis_result=analysis_result,
            use_llm=use_llm,
        )

    async def evaluate_transaction(self, transaction: Transaction) -> FraudAssessment:
        """Evaluate a transaction by coordinating enabled sub-agents and delegating to DecisionAgent."""
        return await self.coordinate_evaluation(transaction)


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
        f"[bold]Tools Invoked:[/bold] {', '.join(assessment.tools_invoked)}\n\n"
        f"[italic]{assessment.reasoning_summary}[/italic]"
    )

    console.print(Panel(summary_text, title="Fraud Scorer Assessment", border_style=color))
    console.print(table)
    console.print()


async def _async_demo() -> None:
    """Run sample normal and fraudulent transactions through the multi-agent orchestrator."""
    orchestrator = OrchestratorAgent()
    ollama_up = is_ollama_available(orchestrator.ollama_base_url)

    mode_str = (
        f"Ollama Local LLM ({orchestrator.model_name} @ {orchestrator.ollama_base_url})"
        if ollama_up
        else "Multi-Agent Skill Mode (Ollama not detected on localhost:11434)"
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
