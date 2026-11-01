"""Transaction Amount Anomaly Skill (`src/fraud_scorer/skills/amount_anomaly_skill.py`)."""

from typing import Any

from fraud_scorer.models.transaction import RiskFactor, Transaction


class AmountAnomalySkill:
    """Skill for evaluating spend anomalies relative to account baseline and card-present status."""

    name: str = "amount_anomaly_skill"
    description: str = (
        "Compares transaction amount against historical account average spend and payment "
        "presence (card-not-present vs. card-present) to detect spend spikes."
    )

    def execute(
        self,
        transaction: Transaction,
        account_history: dict[str, Any] | None = None,
    ) -> list[RiskFactor]:
        """Evaluate transaction amount anomalies against account history baseline."""
        risk_factors: list[RiskFactor] = []
        avg_amt = float((account_history or {}).get("avg_transaction_amount", 50.0) or 50.0)

        if transaction.amount > max(avg_amt * 5.0, 500.0):
            ratio = round(transaction.amount / max(avg_amt, 1.0), 1)
            contrib = 35.0 if not transaction.payment_method.is_card_present else 20.0
            risk_factors.append(
                RiskFactor(
                    category="AMOUNT_ANOMALY",
                    severity="HIGH" if ratio >= 10 else "MEDIUM",
                    contribution_score=contrib,
                    description=(
                        f"Transaction amount (${transaction.amount:,.2f}) is {ratio}x higher "
                        f"than historical account average (${avg_amt:,.2f})."
                    ),
                    details={
                        "transaction_amount": transaction.amount,
                        "avg_transaction_amount": avg_amt,
                        "ratio": ratio,
                        "is_card_present": transaction.payment_method.is_card_present,
                    },
                )
            )

        return risk_factors
