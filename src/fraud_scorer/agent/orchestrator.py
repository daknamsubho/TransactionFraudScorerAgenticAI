"""Agentic Orchestrator for evaluating transactions using MCP tools."""

import argparse
import asyncio
from datetime import UTC, datetime

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from fraud_scorer.config import settings
from fraud_scorer.mcp.tools.risk_tools import (
    check_geo_anomaly,
    check_merchant_risk,
    check_velocity,
    lookup_account_history,
)
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

console = Console()


class FraudScorerOrchestrator:
    """Orchestrates transaction fraud scoring using MCP risk tools and reasoning."""

    def __init__(self, provider: str | None = None) -> None:
        self.provider = provider or settings.default_llm_provider

    async def evaluate_transaction(self, tx: Transaction) -> FraudAssessment:
        """Evaluate a transaction by calling MCP tools and aggregating risk evidence.

        Args:
            tx: Target Transaction model.

        Returns:
            Comprehensive FraudAssessment with risk factors, score, and decision.
        """
        tools_called: list[str] = []
        risk_factors: list[RiskFactor] = []

        # 1. Query Account History via MCP tool
        tools_called.append("lookup_account_history")
        acct_history = lookup_account_history(account_id=tx.account_id)
        if acct_history["account_risk_score"] > 20.0:
            severity: RiskSeverity = "CRITICAL" if acct_history["account_risk_score"] >= 75.0 else "MEDIUM"
            risk_factors.append(
                RiskFactor(
                    category="ACCOUNT_PROFILE",
                    severity=severity,
                    contribution_score=acct_history["account_risk_score"],
                    description=acct_history["reasoning"],
                    details=acct_history,
                )
            )

        # 2. Query Velocity via MCP tool
        tools_called.append("check_velocity")
        velocity_info = check_velocity(account_id=tx.account_id, window_minutes=60)
        if velocity_info["velocity_risk_score"] > 20.0:
            severity = "CRITICAL" if velocity_info["is_burst"] else "HIGH"
            risk_factors.append(
                RiskFactor(
                    category="VELOCITY",
                    severity=severity,
                    contribution_score=velocity_info["velocity_risk_score"],
                    description=velocity_info["reasoning"],
                    details=velocity_info,
                )
            )

        # 3. Query Geo Anomaly via MCP tool
        tools_called.append("check_geo_anomaly")
        geo_info = check_geo_anomaly(
            account_id=tx.account_id,
            current_lat=tx.location.latitude,
            current_lon=tx.location.longitude,
            current_timestamp_iso=tx.timestamp.isoformat(),
        )
        if geo_info["geo_risk_score"] > 20.0:
            severity = "CRITICAL" if geo_info["impossible_travel"] else "MEDIUM"
            risk_factors.append(
                RiskFactor(
                    category="GEO_ANOMALY",
                    severity=severity,
                    contribution_score=geo_info["geo_risk_score"],
                    description=geo_info["reasoning"],
                    details=geo_info,
                )
            )

        # 4. Query Merchant Risk via MCP tool
        tools_called.append("check_merchant_risk")
        merchant_info = check_merchant_risk(
            merchant_id=tx.merchant.merchant_id,
            mcc=tx.merchant.mcc,
        )
        if merchant_info["merchant_risk_score"] > 20.0:
            risk_factors.append(
                RiskFactor(
                    category="MERCHANT_RISK",
                    severity="HIGH",
                    contribution_score=merchant_info["merchant_risk_score"],
                    description=merchant_info["reasoning"],
                    details=merchant_info,
                )
            )

        # 5. Amount Anomaly Check
        if tx.amount >= 2000.0:
            risk_factors.append(
                RiskFactor(
                    category="AMOUNT_ANOMALY",
                    severity="HIGH" if tx.amount >= 5000.0 else "MEDIUM",
                    contribution_score=min(85.0, 30.0 + (tx.amount / 100.0)),
                    description=f"High transaction value (${tx.amount:,.2f}) exceeding standard threshold.",
                    details={"amount": tx.amount},
                )
            )

        # Synthesize Overall Risk Score
        overall_score = self._compute_overall_risk_score(risk_factors)
        decision = self._resolve_decision(overall_score, risk_factors)
        rationale = self._generate_reasoning_summary(decision, overall_score, risk_factors)

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

    def _compute_overall_risk_score(self, risk_factors: list[RiskFactor]) -> float:
        """Compute normalized composite risk score (0-100) from detected risk factors."""
        if not risk_factors:
            return 5.0  # Baseline safe score

        # If any factor is CRITICAL, score is weighted heavily towards max
        max_score = max(f.contribution_score for f in risk_factors)
        has_critical = any(f.severity == "CRITICAL" for f in risk_factors)

        if has_critical:
            # Critical anomalies take precedence
            return round(min(100.0, max_score + len(risk_factors) * 2.0), 1)

        # Weighted aggregate for moderate signals
        avg_score = sum(f.contribution_score for f in risk_factors) / len(risk_factors)
        composite = 0.65 * max_score + 0.35 * avg_score
        return round(min(100.0, composite), 1)

    def _resolve_decision(self, score: float, risk_factors: list[RiskFactor]) -> RiskDecision:
        """Map numeric score and critical triggers to final disposition."""
        has_critical = any(f.severity == "CRITICAL" for f in risk_factors)
        if score >= 70.0 or has_critical:
            return "DECLINE"
        if score >= 30.0:
            return "REVIEW"
        return "APPROVE"

    def _generate_reasoning_summary(self, decision: RiskDecision, score: float, risk_factors: list[RiskFactor]) -> str:
        """Create human-readable audit rationale."""
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


async def run_demo() -> None:
    """Run an interactive demonstration scoring both a legitimate and a high-risk transaction."""
    orchestrator = FraudScorerOrchestrator()
    console.print(
        Panel(
            "[bold green]Starting Transaction Fraud Scorer Agent Demo[/]\n"
            "Testing 2 scenarios against registered MCP tools: Safe baseline & Multi-vector fraud.",
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
            mcc="5499",  # Misc Food Stores
        ),
    )

    console.print("[bold cyan]Scenario 1: Evaluating normal local transaction...[/]")
    assessment_1 = await orchestrator.evaluate_transaction(tx_normal)
    display_assessment(tx_normal, assessment_1)

    # Scenario 2: Suspicious transaction (high amount, impossible travel, high-risk MCC, new account)
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
            mcc="7995",  # High-risk gambling
        ),
    )

    console.print("[bold red]Scenario 2: Evaluating high-risk multi-vector transaction...[/]")
    assessment_2 = await orchestrator.evaluate_transaction(tx_suspicious)
    display_assessment(tx_suspicious, assessment_2)


def main() -> None:
    """CLI entrypoint for running the fraud scorer agent."""
    parser = argparse.ArgumentParser(description="Transaction Fraud Scorer Agent")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run end-to-end demo evaluating sample legitimate & fraudulent transactions.",
    )
    args = parser.parse_args()

    if args.demo or len(sys.argv) == 1:
        asyncio.run(run_demo())
    else:
        parser.print_help()


if __name__ == "__main__":
    import sys

    main()
