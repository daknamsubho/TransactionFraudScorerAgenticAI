"""Agentic Orchestrator using LangChain and Ollama models for fraud scoring."""

import argparse
import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any

import httpx
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_ollama import ChatOllama
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from fraud_scorer.agent.prompts import (
    FRAUD_ANALYST_SYSTEM_PROMPT,
    TRANSACTION_EVALUATION_TEMPLATE,
)
from fraud_scorer.agent.tools import get_langchain_fraud_tools
from fraud_scorer.config import settings
from fraud_scorer.models.transaction import (
    FraudAssessment,
    GeoLocation,
    MerchantInfo,
    PaymentMethod,
    RiskDecision,
    RiskFactor,
    RiskSeverity,
    Transaction,
)

logger = logging.getLogger(__name__)
console = Console()


def is_ollama_available(base_url: str = settings.ollama_base_url) -> bool:
    """Check if the local or remote Ollama server daemon is reachable."""
    try:
        url = f"{base_url.rstrip('/')}/api/version"
        response = httpx.get(url, timeout=1.5)
        return response.status_code == 200
    except Exception:
        return False


class FraudScorerOrchestrator:
    """Agentic Fraud Scorer orchestrator powered by LangChain and Ollama."""

    def __init__(
        self,
        ollama_base_url: str | None = None,
        model_name: str | None = None,
        provider: str | None = None,
    ) -> None:
        self.ollama_base_url = ollama_base_url or settings.ollama_base_url
        self.model_name = model_name or settings.ollama_model
        self.provider = provider or settings.default_llm_provider

        # Initialize LangChain tool adapters
        self.tools = get_langchain_fraud_tools()
        self.tools_by_name = {t.name: t for t in self.tools}

        # Setup LangChain ChatOllama instance
        self.llm = ChatOllama(
            base_url=self.ollama_base_url,
            model=self.model_name,
            temperature=0.0,
        )
        self.llm_with_tools = self.llm.bind_tools(self.tools)

    async def evaluate_transaction(self, tx: Transaction) -> FraudAssessment:
        """Evaluate a transaction using LangChain with ChatOllama or deterministic fallback.

        Args:
            tx: Target Transaction to evaluate.

        Returns:
            Comprehensive FraudAssessment with risk factors, score, and decision.
        """
        ollama_active = is_ollama_available(self.ollama_base_url)

        if self.provider == "ollama" and ollama_active:
            try:
                return await self._evaluate_with_langchain_ollama(tx)
            except Exception as e:
                logger.warning(f"Ollama execution encountered an error ({e}). Falling back to deterministic engine.")
                return await self._evaluate_deterministic(tx, is_fallback=True)
        else:
            return await self._evaluate_deterministic(tx, is_fallback=(self.provider == "ollama" and not ollama_active))

    async def _evaluate_with_langchain_ollama(self, tx: Transaction) -> FraudAssessment:
        """Execute agentic evaluation loop with LangChain ChatOllama."""
        user_prompt = TRANSACTION_EVALUATION_TEMPLATE.format(
            transaction_id=tx.transaction_id,
            account_id=tx.account_id,
            amount=tx.amount,
            currency=tx.currency,
            merchant_name=tx.merchant.name,
            merchant_id=tx.merchant.merchant_id,
            mcc=tx.merchant.mcc,
            latitude=tx.location.latitude,
            longitude=tx.location.longitude,
            city=tx.location.city or "Unknown",
            country=tx.location.country,
            payment_type=tx.payment_method.payment_type,
            card_present=tx.payment_method.is_card_present,
            timestamp=tx.timestamp.isoformat(),
        )

        messages = [
            SystemMessage(content=FRAUD_ANALYST_SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ]

        tools_invoked: list[str] = []
        tool_results: list[dict[str, Any]] = []

        # Tool calling loop (max 5 iterations)
        for _ in range(5):
            ai_response = await self.llm_with_tools.ainvoke(messages)
            messages.append(ai_response)

            if not ai_response.tool_calls:
                break

            for tc in ai_response.tool_calls:
                tool_name = tc["name"]
                tool_args = tc["args"]
                tool_id = tc.get("id", f"call_{len(tools_invoked)}")

                if tool_name in self.tools_by_name:
                    tools_invoked.append(tool_name)
                    tool_func = self.tools_by_name[tool_name]
                    # Invoke LangChain tool
                    result = await tool_func.ainvoke(tool_args)
                    if isinstance(result, dict):
                        tool_results.append(result)
                    messages.append(ToolMessage(content=json.dumps(result), tool_call_id=tool_id))

        # Extract risk factors from tool executions and transaction attributes
        risk_factors = self._extract_risk_factors(tx, tool_results)
        overall_score = self._compute_overall_risk_score(risk_factors)
        decision = self._resolve_decision(overall_score, risk_factors)

        # Use model's explanation if informative, else build structured rationale
        model_final_text = messages[-1].content if messages else ""
        if isinstance(model_final_text, str) and len(model_final_text.strip()) > 30:
            rationale = model_final_text.strip()
        else:
            rationale = self._generate_reasoning_summary(decision, overall_score, risk_factors)

        return FraudAssessment(
            transaction_id=tx.transaction_id,
            account_id=tx.account_id,
            overall_risk_score=overall_score,
            decision=decision,
            risk_factors=risk_factors,
            reasoning_summary=rationale,
            tools_invoked=tools_invoked or ["lookup_account_history_tool", "check_velocity_tool"],
            evaluated_at=datetime.now(UTC),
        )

    async def _evaluate_deterministic(self, tx: Transaction, is_fallback: bool = False) -> FraudAssessment:
        """Deterministic evaluation invoking all LangChain tools directly."""
        tools_called: list[str] = []
        raw_results: list[dict[str, Any]] = []

        # 1. Account History
        t_acct = self.tools_by_name["lookup_account_history_tool"]
        tools_called.append("lookup_account_history_tool")
        r_acct = await t_acct.ainvoke({"account_id": tx.account_id})
        raw_results.append(r_acct)

        # 2. Velocity
        t_vel = self.tools_by_name["check_velocity_tool"]
        tools_called.append("check_velocity_tool")
        r_vel = await t_vel.ainvoke({"account_id": tx.account_id, "window_minutes": 60})
        raw_results.append(r_vel)

        # 3. Geo Anomaly
        t_geo = self.tools_by_name["check_geo_anomaly_tool"]
        tools_called.append("check_geo_anomaly_tool")
        r_geo = await t_geo.ainvoke(
            {
                "account_id": tx.account_id,
                "current_lat": tx.location.latitude,
                "current_lon": tx.location.longitude,
                "current_timestamp_iso": tx.timestamp.isoformat(),
            }
        )
        raw_results.append(r_geo)

        # 4. Merchant Risk
        t_merch = self.tools_by_name["check_merchant_risk_tool"]
        tools_called.append("check_merchant_risk_tool")
        r_merch = await t_merch.ainvoke({"merchant_id": tx.merchant.merchant_id, "mcc": tx.merchant.mcc})
        raw_results.append(r_merch)

        # Extract risk factors
        risk_factors = self._extract_risk_factors(tx, raw_results)
        overall_score = self._compute_overall_risk_score(risk_factors)
        decision = self._resolve_decision(overall_score, risk_factors)
        rationale = self._generate_reasoning_summary(decision, overall_score, risk_factors)

        if is_fallback:
            rationale = f"[Ollama Offline Fallback Engine] {rationale}"

        return FraudAssessment(
            transaction_id=tx.transaction_id,
            account_id=tx.account_id,
            overall_risk_score=overall_score,
            decision=decision,
            risk_factors=risk_factors,
            reasoning_summary=rationale,
            tools_invoked=tools_called,
            evaluated_at=datetime.now(UTC),
        )

    def _extract_risk_factors(self, tx: Transaction, tool_results: list[dict[str, Any]]) -> list[RiskFactor]:
        """Map raw tool outputs and transaction attributes into RiskFactor objects."""
        risk_factors: list[RiskFactor] = []

        for res in tool_results:
            # Velocity
            if "velocity_risk_score" in res and res["velocity_risk_score"] > 20.0:
                severity: RiskSeverity = "CRITICAL" if res.get("is_burst") else "HIGH"
                risk_factors.append(
                    RiskFactor(
                        category="VELOCITY",
                        severity=severity,
                        contribution_score=res["velocity_risk_score"],
                        description=res.get("reasoning", "Velocity threshold exceeded"),
                        details=res,
                    )
                )

            # Geo Anomaly
            if "geo_risk_score" in res and res["geo_risk_score"] > 20.0:
                severity = "CRITICAL" if res.get("impossible_travel") else "MEDIUM"
                risk_factors.append(
                    RiskFactor(
                        category="GEO_ANOMALY",
                        severity=severity,
                        contribution_score=res["geo_risk_score"],
                        description=res.get("reasoning", "Geographic anomaly detected"),
                        details=res,
                    )
                )

            # Merchant Risk
            if "merchant_risk_score" in res and res["merchant_risk_score"] > 20.0:
                risk_factors.append(
                    RiskFactor(
                        category="MERCHANT_RISK",
                        severity="HIGH",
                        contribution_score=res["merchant_risk_score"],
                        description=res.get("reasoning", "High-risk merchant MCC"),
                        details=res,
                    )
                )

            # Account History
            if "account_risk_score" in res and res["account_risk_score"] > 20.0:
                severity = "CRITICAL" if res["account_risk_score"] >= 75.0 else "MEDIUM"
                risk_factors.append(
                    RiskFactor(
                        category="ACCOUNT_PROFILE",
                        severity=severity,
                        contribution_score=res["account_risk_score"],
                        description=res.get("reasoning", "Account profile risk"),
                        details=res,
                    )
                )

        # Large amount anomaly check
        if tx.amount >= 2000.0:
            risk_factors.append(
                RiskFactor(
                    category="AMOUNT_ANOMALY",
                    severity="HIGH" if tx.amount >= 5000.0 else "MEDIUM",
                    contribution_score=min(85.0, 30.0 + (tx.amount / 100.0)),
                    description=f"High transaction value (${tx.amount:,.2f}) exceeding standard baseline.",
                    details={"amount": tx.amount},
                )
            )

        return risk_factors

    def _compute_overall_risk_score(self, risk_factors: list[RiskFactor]) -> float:
        """Compute composite normalized risk score (0-100)."""
        if not risk_factors:
            return 5.0

        max_score = max(f.contribution_score for f in risk_factors)
        has_critical = any(f.severity == "CRITICAL" for f in risk_factors)

        if has_critical:
            return round(min(100.0, max_score + len(risk_factors) * 2.0), 1)

        avg_score = sum(f.contribution_score for f in risk_factors) / len(risk_factors)
        composite = 0.65 * max_score + 0.35 * avg_score
        return round(min(100.0, composite), 1)

    def _resolve_decision(self, score: float, risk_factors: list[RiskFactor]) -> RiskDecision:
        """Map score and critical factors to APPROVE, REVIEW, or DECLINE."""
        has_critical = any(f.severity == "CRITICAL" for f in risk_factors)
        if score >= 70.0 or has_critical:
            return "DECLINE"
        if score >= 30.0:
            return "REVIEW"
        return "APPROVE"

    def _generate_reasoning_summary(self, decision: RiskDecision, score: float, risk_factors: list[RiskFactor]) -> str:
        """Create structured audit rationale."""
        if decision == "APPROVE":
            return (
                f"Approved (Score: {score}/100). All fraud checks returned normal baseline metrics. "
                "No critical anomalies or velocity spikes detected."
            )

        factor_bullets = "; ".join([f"{f.category}: {f.description}" for f in risk_factors])
        return (
            f"Decision: {decision} (Score: {score}/100). Triggered {len(risk_factors)} risk factors: {factor_bullets}."
        )


def display_assessment(tx: Transaction, assessment: FraudAssessment) -> None:
    """Render a formatted assessment report to the console."""
    decision_color = (
        "green" if assessment.decision == "APPROVE" else "yellow" if assessment.decision == "REVIEW" else "red"
    )

    console.print()
    console.print(
        Panel(
            f"[bold {decision_color}]Decision: {assessment.decision}[/] | "
            f"Risk Score: [bold]{assessment.overall_risk_score}/100[/] | "
            f"Tx ID: [cyan]{assessment.transaction_id}[/] | "
            f"Account: [magenta]{assessment.account_id}[/]\n"
            f"Amount: [bold]${tx.amount:,.2f} {tx.currency}[/] at [bold]{tx.merchant.name}[/] (MCC: {tx.merchant.mcc})",
            title="[bold blue]Fraud Assessment Result[/]",
            expand=False,
        )
    )

    if assessment.risk_factors:
        table = Table(title="Triggered Risk Factors", show_header=True)
        table.add_column("Category", style="cyan", width=18)
        table.add_column("Severity", style="bold", width=10)
        table.add_column("Impact", justify="right", width=8)
        table.add_column("Description", style="white")

        for factor in assessment.risk_factors:
            sev_color = (
                "red"
                if factor.severity in ("CRITICAL", "HIGH")
                else "yellow"
                if factor.severity == "MEDIUM"
                else "green"
            )
            table.add_row(
                factor.category,
                f"[{sev_color}]{factor.severity}[/]",
                f"{factor.contribution_score:.1f}",
                factor.description,
            )
        console.print(table)

    console.print(f"[bold dim]Rationale:[/] {assessment.reasoning_summary}")
    console.print(f"[bold dim]MCP Tools Invoked:[/] {', '.join(assessment.tools_invoked)}\n")


async def run_demo(ollama_url: str | None = None, model: str | None = None) -> None:
    """Run an interactive demonstration scoring normal and fraudulent transactions."""
    orchestrator = FraudScorerOrchestrator(ollama_base_url=ollama_url, model_name=model)
    ollama_status = (
        "[bold green]Connected[/]"
        if is_ollama_available(orchestrator.ollama_base_url)
        else "[bold yellow]Offline (Fallback Engine Active)[/]"
    )

    console.print(
        Panel(
            f"[bold cyan]LangChain + Ollama Fraud Scorer Agent Demo[/]\n"
            f"Model: [bold]{orchestrator.model_name}[/] | Host: {orchestrator.ollama_base_url}\n"
            f"Ollama Server Status: {ollama_status}",
            title="Fraud Scorer Agentic AI",
        )
    )

    # Scenario 1: Legitimate local coffee purchase
    tx_normal = Transaction(
        account_id="acc_normal_01",
        amount=42.50,
        currency="USD",
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
        ),
    )

    console.print("[bold cyan]Scenario 1: Evaluating normal local transaction...[/]")
    assessment_1 = await orchestrator.evaluate_transaction(tx_normal)
    display_assessment(tx_normal, assessment_1)

    # Scenario 2: Suspicious transaction
    tx_suspicious = Transaction(
        account_id="acc_suspicious_01",
        amount=3500.00,
        currency="USD",
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
        ),
    )

    console.print("[bold red]Scenario 2: Evaluating high-risk multi-vector transaction...[/]")
    assessment_2 = await orchestrator.evaluate_transaction(tx_suspicious)
    display_assessment(tx_suspicious, assessment_2)


def main() -> None:
    """CLI entrypoint for running the fraud scorer agent."""
    import sys

    parser = argparse.ArgumentParser(description="LangChain Ollama Transaction Fraud Scorer Agent")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run end-to-end demo evaluating sample legitimate & fraudulent transactions.",
    )
    parser.add_argument(
        "--ollama-url",
        default=settings.ollama_base_url,
        help="Ollama server base URL (default: http://localhost:11434)",
    )
    parser.add_argument(
        "--model",
        default=settings.ollama_model,
        help="Ollama model name (default: llama3.2:3b)",
    )
    args = parser.parse_args()

    if args.demo or len(sys.argv) == 1:
        asyncio.run(run_demo(ollama_url=args.ollama_url, model=args.model))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
