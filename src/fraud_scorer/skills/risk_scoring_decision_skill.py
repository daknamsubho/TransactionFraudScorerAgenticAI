"""Risk Scoring & Decision Skill (`src/fraud_scorer/skills/risk_scoring_decision_skill.py`)."""

from typing import Literal

from fraud_scorer.models.transaction import FraudAssessment, RiskFactor, Transaction


class RiskScoringDecisionSkill:
    """Skill used exclusively by the Decision Agent to compute the composite risk score and disposition."""

    name: str = "risk_scoring_decision_skill"
    description: str = (
        "Aggregates RiskFactor contributions into a normalized 0.0-100.0 risk score, "
        "applies decision taxonomy thresholds (APPROVE < 30, REVIEW 30-69.9, DECLINE >= 70), "
        "and generates an auditable FraudAssessment."
    )

    def execute(
        self,
        transaction: Transaction,
        risk_factors: list[RiskFactor],
        tools_invoked: list[str],
        llm_reasoning_notes: str | None = None,
    ) -> FraudAssessment:
        """Compute normalized risk score, disposition, and FraudAssessment."""
        total_score = min(
            round(sum(rf.contribution_score for rf in risk_factors), 2),
            100.0,
        )

        decision: Literal["APPROVE", "REVIEW", "DECLINE"]
        if total_score >= 70.0:
            decision = "DECLINE"
        elif total_score >= 30.0:
            decision = "REVIEW"
        else:
            decision = "APPROVE"

        if not risk_factors:
            base_summary = (
                f"Transaction {transaction.transaction_id} (${transaction.amount:,.2f} "
                f"{transaction.currency}) aligns with account '{transaction.account_id}' historical "
                "baseline, geographic location, and low-risk merchant profile. Approved automatically."
            )
        else:
            factor_categories = ", ".join(rf.category for rf in risk_factors)
            base_summary = (
                f"Decision: {decision} (Composite Score: {total_score}/100). "
                f"Triggered {len(risk_factors)} risk factor(s): {factor_categories}."
            )

        if llm_reasoning_notes and llm_reasoning_notes.strip():
            cleaned_notes = " ".join(llm_reasoning_notes.strip().split())
            reasoning_summary = f"{base_summary} [LLM Decision Notes: {cleaned_notes[:320]}]"
        else:
            reasoning_summary = base_summary

        return FraudAssessment(
            transaction_id=transaction.transaction_id,
            account_id=transaction.account_id,
            overall_risk_score=total_score,
            decision=decision,
            risk_factors=risk_factors,
            reasoning_summary=reasoning_summary,
            tools_invoked=list(dict.fromkeys(tools_invoked)),
        )
