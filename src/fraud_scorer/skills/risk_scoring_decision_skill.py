"""Risk Scoring & Decision Skill (`src/fraud_scorer/skills/risk_scoring_decision_skill.py`)."""

from typing import Any, Literal

from fraud_scorer.models.transaction import FraudAssessment, RiskFactor, Transaction


class RiskScoringDecisionSkill:
    """Skill used exclusively by the Decision Agent to compute the composite risk score and disposition."""

    name: str = "risk_scoring_decision_skill"
    description: str = (
        "Aggregates RiskFactor contributions into a normalized 0.0-100.0 risk score, "
        "applies decision taxonomy thresholds (APPROVE < 30, REVIEW 30-69.9, DECLINE >= 70) "
        "and ChromaDB RAG policy grounding, and generates an auditable FraudAssessment."
    )

    def execute(
        self,
        transaction: Transaction,
        risk_factors: list[RiskFactor],
        tools_invoked: list[str],
        llm_reasoning_notes: str | None = None,
        rag_policies: list[dict[str, Any]] | None = None,
        evaluator_feedback: str | None = None,
    ) -> FraudAssessment:
        """Compute normalized risk score, disposition, and FraudAssessment."""
        total_score = min(
            round(sum(rf.contribution_score for rf in risk_factors), 2),
            100.0,
        )

        # Enforce mandatory policy floor if CRITICAL GEO_ANOMALY (impossible travel) is present
        has_critical_geo = any(
            rf.category == "GEO_ANOMALY" and rf.severity == "CRITICAL" for rf in risk_factors
        )
        if has_critical_geo and total_score < 70.0:
            total_score = max(total_score, 75.0)

        decision: Literal["APPROVE", "REVIEW", "DECLINE"]
        if total_score >= 70.0:
            decision = "DECLINE"
        elif total_score >= 30.0:
            decision = "REVIEW"
        else:
            decision = "APPROVE"

        policy_citations: list[str] = []
        if rag_policies:
            for pol in rag_policies[:2]:
                c_id = pol.get("clause_id") or (pol.get("metadata") or {}).get("clause_id")
                if c_id and c_id not in policy_citations:
                    policy_citations.append(str(c_id))

        citation_suffix = f" Grounded in policy clause(s): {', '.join(policy_citations)}." if policy_citations else ""

        if not risk_factors:
            base_summary = (
                f"Transaction {transaction.transaction_id} (${transaction.amount:,.2f} "
                f"{transaction.currency}) aligns with account '{transaction.account_id}' historical "
                f"baseline, geographic location, and low-risk merchant profile. Approved automatically.{citation_suffix}"
            )
        else:
            factor_categories = ", ".join(rf.category for rf in risk_factors)
            base_summary = (
                f"Decision: {decision} (Composite Score: {total_score}/100). "
                f"Triggered {len(risk_factors)} risk factor(s): {factor_categories}.{citation_suffix}"
            )

        if evaluator_feedback and evaluator_feedback.strip():
            cleaned_fb = " ".join(evaluator_feedback.strip().split())
            base_summary = f"{base_summary} [Remediated per Evaluator: {cleaned_fb[:200]}]"

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
