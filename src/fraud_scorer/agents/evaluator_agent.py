"""Evaluator Agent (`src/fraud_scorer/agents/evaluator_agent.py`).

Implements the Critic in the Actor-Critic topology using Tier 3+ Auditor LLM
(`qwen3.8:27b` with automatic local Ollama fallback) as specified in
`docs/agentic-architecture-pattern.md`.
"""

from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama
from pydantic import BaseModel, Field

from fraud_scorer.config import resolve_ollama_model, settings
from fraud_scorer.models.transaction import FraudAssessment, Transaction

EVALUATOR_AGENT_SYSTEM_PROMPT = """You are the Evaluator Agent (Critic — Tier 3+ Adversarial Compliance Auditor) in a financial fraud detection system.
Your role is to audit the Decision Agent's draft FraudAssessment for:
1. Mathematical consistency: The overall_risk_score must align with the sum of RiskFactor contribution_scores (capped at 100.0) or mandatory policy floors.
2. Policy compliance:
   - Score < 30.0 -> APPROVE
   - Score 30.0 to 69.9 -> REVIEW
   - Score >= 70.0 -> DECLINE
   - Any transaction with a CRITICAL GEO_ANOMALY (impossible travel) MUST NOT be APPROVE.
3. Explainability & evidence grounding: The reasoning_summary must be non-empty and reference the detected risk factors.
Emit a concise audit note confirming integrity or detailing the required remediation."""

RejectionCategory = Literal[
    "ARITHMETIC_ERROR",
    "UNGROUNDED_ASSERTION",
    "POLICY_CONTRADICTION",
    "INSUFFICIENT_EVIDENCE",
]


class EvaluatorVerdict(BaseModel):
    """Structured audit verdict emitted by the Evaluator Agent (Critic)."""

    verdict: Literal["ACCEPTED", "REJECTED"] = Field(
        ...,
        description="Whether the draft assessment passes quality and policy checks.",
    )
    rejection_category: RejectionCategory | None = Field(
        default=None,
        description="Category of failure when verdict == 'REJECTED'.",
    )
    target_agent: Literal["decision", "analysis"] | None = Field(
        default=None,
        description="Target agent to re-invoke during targeted differential feedback loop.",
    )
    remediation_instruction: str | None = Field(
        default=None,
        description="Actionable remediation instruction for the target agent.",
    )
    audit_notes: str = Field(
        default="Assessment verified against mathematical, taxonomy, and policy rubrics.",
        description="Detailed explanation of the audit outcome.",
    )
    model_used: str | None = None


class EvaluatorAgent:
    """Adversarial Critic Agent that audits DecisionAgent assessments for math, policy, and explainability."""

    def __init__(
        self,
        ollama_base_url: str | None = None,
        model_name: str | None = None,
        score_tolerance: float = 5.0,
    ) -> None:
        self.ollama_base_url = ollama_base_url or settings.ollama_base_url
        self.preferred_model = model_name or settings.evaluator_model
        self.model_name = self.preferred_model
        self.score_tolerance = score_tolerance

    def _get_resolved_model(self) -> str:
        """Resolve Tier 3+ model (`qwen3.8:27b`) against installed Ollama models with fallback."""
        return resolve_ollama_model(
            preferred_model=self.preferred_model,
            fallback_model=settings.ollama_model,
            base_url=self.ollama_base_url,
        )

    async def evaluate_assessment(
        self,
        transaction: Transaction,
        draft_assessment: FraudAssessment,
        rag_policies: list[dict[str, Any]] | None = None,
        use_llm: bool = False,
    ) -> EvaluatorVerdict:
        """Audit a draft FraudAssessment across mathematical, policy, and explainability rubrics."""
        resolved_model = self.preferred_model
        factors = draft_assessment.risk_factors
        expected_sum = min(round(sum(rf.contribution_score for rf in factors), 2), 100.0)
        has_critical_geo = any(
            rf.category == "GEO_ANOMALY" and rf.severity == "CRITICAL" for rf in factors
        )
        if has_critical_geo and expected_sum < 70.0:
            expected_sum = max(expected_sum, 75.0)

        actual_score = draft_assessment.overall_risk_score
        actual_decision = draft_assessment.decision

        # 1. Policy Contradiction Check: Critical Geo / Impossible Travel cannot be APPROVE
        if has_critical_geo and actual_decision == "APPROVE":
            return EvaluatorVerdict(
                verdict="REJECTED",
                rejection_category="POLICY_CONTRADICTION",
                target_agent="decision",
                remediation_instruction=(
                    "Transaction has a CRITICAL GEO_ANOMALY (impossible travel). "
                    "Per policy, disposition MUST be DECLINE or REVIEW, never APPROVE."
                ),
                audit_notes="Rejected due to CRITICAL GEO_ANOMALY disposition contradiction.",
                model_used=resolved_model,
            )

        # 2. Mathematical Consistency Check (score vs sum of risk factor contributions)
        if abs(actual_score - expected_sum) > self.score_tolerance:
            return EvaluatorVerdict(
                verdict="REJECTED",
                rejection_category="ARITHMETIC_ERROR",
                target_agent="decision",
                remediation_instruction=(
                    f"Overall risk score ({actual_score}) deviates from mathematical sum of "
                    f"risk factor contributions ({expected_sum}) by more than {self.score_tolerance} points. "
                    f"Recalculate composite score to {expected_sum}."
                ),
                audit_notes=f"Rejected due to arithmetic mismatch: actual={actual_score}, expected={expected_sum}.",
                model_used=resolved_model,
            )

        # 3. Taxonomy Threshold Alignment Check
        expected_decision: Literal["APPROVE", "REVIEW", "DECLINE"]
        if actual_score >= 70.0:
            expected_decision = "DECLINE"
        elif actual_score >= 30.0:
            expected_decision = "REVIEW"
        else:
            expected_decision = "APPROVE"

        if actual_decision != expected_decision:
            return EvaluatorVerdict(
                verdict="REJECTED",
                rejection_category="POLICY_CONTRADICTION",
                target_agent="decision",
                remediation_instruction=(
                    f"Disposition '{actual_decision}' violates score taxonomy for score {actual_score}. "
                    f"Expected disposition '{expected_decision}' (APPROVE < 30, REVIEW 30-69.9, DECLINE >= 70)."
                ),
                audit_notes=(
                    f"Rejected due to taxonomy threshold mismatch: score={actual_score} "
                    f"requires {expected_decision}, got {actual_decision}."
                ),
                model_used=resolved_model,
            )

        # 4. Explainability & Grounding Check
        summary = (draft_assessment.reasoning_summary or "").strip()
        if len(summary) < 10:
            return EvaluatorVerdict(
                verdict="REJECTED",
                rejection_category="UNGROUNDED_ASSERTION",
                target_agent="decision",
                remediation_instruction=(
                    "Reasoning summary is missing or too brief. Provide a grounded explanation "
                    "citing the triggered risk factors and composite score."
                ),
                audit_notes="Rejected due to empty or insufficient reasoning_summary.",
                model_used=resolved_model,
            )

        if factors and not any(rf.category in summary for rf in factors):
            return EvaluatorVerdict(
                verdict="REJECTED",
                rejection_category="UNGROUNDED_ASSERTION",
                target_agent="decision",
                remediation_instruction=(
                    "Reasoning summary fails to cite any of the detected RiskFactor categories "
                    f"({', '.join(rf.category for rf in factors)}). Include explicit factor citations."
                ),
                audit_notes="Rejected because reasoning_summary did not cite detected risk factors.",
                model_used=resolved_model,
            )

        llm_audit_note = "Assessment verified against mathematical, taxonomy, and policy rubrics."
        if use_llm:
            try:
                resolved_model = self._get_resolved_model()
                llm = ChatOllama(
                    base_url=self.ollama_base_url,
                    model=resolved_model,
                    temperature=0.0,
                )
                messages = [
                    SystemMessage(content=EVALUATOR_AGENT_SYSTEM_PROMPT),
                    HumanMessage(
                        content=(
                            f"Audit FraudAssessment for tx={transaction.transaction_id}: "
                            f"score={actual_score}, decision={actual_decision}, "
                            f"factors={[rf.category for rf in factors]}, "
                            f"summary='{summary}'."
                        )
                    ),
                ]
                response = await llm.ainvoke(messages)
                if response.content:
                    llm_audit_note = str(response.content).strip()
            except Exception:
                pass

        return EvaluatorVerdict(
            verdict="ACCEPTED",
            rejection_category=None,
            target_agent=None,
            remediation_instruction=None,
            audit_notes=llm_audit_note,
            model_used=resolved_model,
        )
