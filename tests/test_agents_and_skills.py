"""Unit and integration tests for LangGraph Agents, Skills, Evaluator Critic, and AgentFeatureFlags (PRD-009 & PRD-017)."""

import pytest

from fraud_scorer.agents.analysis_agent import AnalysisAgent
from fraud_scorer.agents.data_retriever_agent import DataRetrieverAgent
from fraud_scorer.agents.decision_agent import DecisionAgent
from fraud_scorer.agents.evaluator_agent import EvaluatorAgent
from fraud_scorer.agents.orchestrator_agent import OrchestratorAgent
from fraud_scorer.config import AgentFeatureFlags, AgentModelConfig
from fraud_scorer.models.transaction import FraudAssessment, Transaction
from fraud_scorer.skills.account_history_skill import AccountHistorySkill
from fraud_scorer.skills.amount_anomaly_skill import AmountAnomalySkill
from fraud_scorer.skills.geo_anomaly_skill import GeoAnomalySkill
from fraud_scorer.skills.merchant_risk_skill import MerchantRiskSkill
from fraud_scorer.skills.policy_retrieval_skill import PolicyRetrievalSkill
from fraud_scorer.skills.risk_scoring_decision_skill import RiskScoringDecisionSkill
from fraud_scorer.skills.velocity_analysis_skill import VelocityAnalysisSkill


@pytest.mark.asyncio
async def test_individual_skills(
    normal_transaction: Transaction,
    fraudulent_transaction: Transaction,
) -> None:
    """Verify each of the 7 separate skill files executes and returns structured evidence."""
    # 1. AccountHistorySkill (SQLite)
    acc_skill = AccountHistorySkill()
    assert acc_skill.get_langchain_tool().name == "lookup_account_history_tool"
    norm_hist, norm_acc_factors, tool_name = await acc_skill.execute(normal_transaction.account_id)
    assert tool_name == "lookup_account_history_tool"
    assert norm_hist["trust_tier"] == "established"
    assert len(norm_acc_factors) == 0

    susp_hist, susp_acc_factors, _ = await acc_skill.execute(fraudulent_transaction.account_id)
    assert susp_hist["trust_tier"] == "untrusted"
    assert len(susp_acc_factors) == 1
    assert susp_acc_factors[0].category == "ACCOUNT_HISTORY"

    # 2. PolicyRetrievalSkill (ChromaDB RAG)
    pol_skill = PolicyRetrievalSkill()
    assert pol_skill.get_langchain_tool().name == "query_fraud_policies_tool"
    pols_2026, pol_tool_name = await pol_skill.execute(
        transaction=fraudulent_transaction,
        policy_year="2026",
        n_results=2,
    )
    assert pol_tool_name == "query_fraud_policies_tool"
    assert len(pols_2026) == 2
    assert all(p["policy_year"] == "2026" for p in pols_2026)

    # 3. VelocityAnalysisSkill
    vel_skill = VelocityAnalysisSkill()
    assert vel_skill.get_langchain_tool().name == "check_velocity_tool"
    _, susp_vel_factors, _ = await vel_skill.execute(fraudulent_transaction.account_id, 60)
    assert len(susp_vel_factors) == 1
    assert susp_vel_factors[0].category == "VELOCITY"

    # 4. GeoAnomalySkill
    geo_skill = GeoAnomalySkill()
    assert geo_skill.get_langchain_tool().name == "check_geo_anomaly_tool"
    _, susp_geo_factors, _ = await geo_skill.execute(
        account_id=fraudulent_transaction.account_id,
        current_lat=fraudulent_transaction.location.latitude,
        current_lon=fraudulent_transaction.location.longitude,
        current_timestamp_iso="2026-10-12T11:30:00Z",
    )
    assert len(susp_geo_factors) == 1
    assert susp_geo_factors[0].category == "GEO_ANOMALY"
    assert susp_geo_factors[0].severity == "CRITICAL"

    # 5. MerchantRiskSkill
    merch_skill = MerchantRiskSkill()
    assert merch_skill.get_langchain_tool().name == "check_merchant_risk_tool"
    _, susp_merch_factors, _ = await merch_skill.execute(
        merchant_id=fraudulent_transaction.merchant.merchant_id,
        mcc=fraudulent_transaction.merchant.mcc,
    )
    assert len(susp_merch_factors) == 1
    assert susp_merch_factors[0].category == "MERCHANT_RISK"

    # 6. AmountAnomalySkill
    amt_skill = AmountAnomalySkill()
    amt_factors = amt_skill.execute(fraudulent_transaction, susp_hist)
    assert len(amt_factors) == 1
    assert amt_factors[0].category == "AMOUNT_ANOMALY"

    # 7. RiskScoringDecisionSkill with RAG policy citations
    dec_skill = RiskScoringDecisionSkill()
    all_factors = [*susp_acc_factors, *susp_vel_factors, *susp_geo_factors, *susp_merch_factors, *amt_factors]
    assessment = dec_skill.execute(
        transaction=fraudulent_transaction,
        risk_factors=all_factors,
        tools_invoked=["lookup_account_history_tool", "query_fraud_policies_tool", "check_velocity_tool"],
        rag_policies=pols_2026,
    )
    assert assessment.decision == "DECLINE"
    assert assessment.overall_risk_score >= 70.0
    assert "Grounded in policy clause(s):" in assessment.reasoning_summary


@pytest.mark.asyncio
async def test_individual_agents_pipeline(
    normal_transaction: Transaction,
    fraudulent_transaction: Transaction,
) -> None:
    """Verify DataRetrieverAgent, AnalysisAgent, DecisionAgent, and EvaluatorAgent operate independently."""
    retriever = DataRetrieverAgent()
    analyzer = AnalysisAgent()
    decider = DecisionAgent()
    evaluator = EvaluatorAgent()

    # Check Heterogeneous Model Tiering defaults (Tier 1: llama3.2:3b, Tier 2: llama3.1:8b, Tier 3: llama3.1:8b)
    assert retriever.model_name == "llama3.2:3b"
    assert analyzer.model_name == "llama3.1:8b"
    assert decider.model_name == "llama3.1:8b"
    assert evaluator.model_name == "llama3.1:8b"

    # Normal flow
    data_res = await retriever.retrieve_data(normal_transaction, use_llm=False)
    assert len(data_res.rag_policies) >= 1
    assert "lookup_account_history_tool" in data_res.tools_invoked
    assert "query_fraud_policies_tool" in data_res.tools_invoked

    analysis_res = await analyzer.analyze_transaction(
        normal_transaction,
        account_history=data_res.account_history,
        use_llm=False,
    )
    decision_res = await decider.make_decision(
        normal_transaction,
        data_result=data_res,
        analysis_result=analysis_res,
        use_llm=False,
    )
    assert decision_res.decision == "APPROVE"
    assert decision_res.overall_risk_score == 0.0

    eval_verdict = await evaluator.evaluate_assessment(normal_transaction, decision_res)
    assert eval_verdict.verdict == "ACCEPTED"

    # Fraudulent flow
    f_data = await retriever.retrieve_data(fraudulent_transaction, use_llm=False)
    f_analysis = await analyzer.analyze_transaction(
        fraudulent_transaction,
        account_history=f_data.account_history,
        use_llm=False,
    )
    f_decision = await decider.make_decision(
        fraudulent_transaction,
        data_result=f_data,
        analysis_result=f_analysis,
        use_llm=False,
    )
    assert f_decision.decision == "DECLINE"
    assert f_decision.overall_risk_score >= 70.0
    assert len(f_decision.risk_factors) >= 4

    f_verdict = await evaluator.evaluate_assessment(fraudulent_transaction, f_decision)
    assert f_verdict.verdict == "ACCEPTED"


@pytest.mark.asyncio
async def test_evaluator_agent_critique_categories(fraudulent_transaction: Transaction) -> None:
    """Verify EvaluatorAgent (Critic) catches arithmetic errors, policy contradictions, and ungrounded summaries."""
    retriever = DataRetrieverAgent()
    analyzer = AnalysisAgent()
    decider = DecisionAgent()
    evaluator = EvaluatorAgent()

    f_data = await retriever.retrieve_data(fraudulent_transaction, use_llm=False)
    f_analysis = await analyzer.analyze_transaction(
        fraudulent_transaction,
        account_history=f_data.account_history,
        use_llm=False,
    )
    valid_decision = await decider.make_decision(
        fraudulent_transaction,
        data_result=f_data,
        analysis_result=f_analysis,
        use_llm=False,
    )

    # 1. Policy Contradiction: CRITICAL GEO_ANOMALY marked APPROVE
    bad_policy_draft = valid_decision.model_copy(update={"decision": "APPROVE"})
    verdict_policy = await evaluator.evaluate_assessment(fraudulent_transaction, bad_policy_draft)
    assert verdict_policy.verdict == "REJECTED"
    assert verdict_policy.rejection_category == "POLICY_CONTRADICTION"
    assert verdict_policy.target_agent == "decision"

    # 2. Arithmetic Error: Score set to 15.0 despite 100.0 sum of risk factors
    non_crit_factors = [
        rf.model_copy(update={"severity": "HIGH"}) for rf in valid_decision.risk_factors
    ]
    bad_math_draft = valid_decision.model_copy(
        update={
            "overall_risk_score": 15.0,
            "decision": "APPROVE",
            "risk_factors": non_crit_factors,
        }
    )
    verdict_math = await evaluator.evaluate_assessment(fraudulent_transaction, bad_math_draft)
    assert verdict_math.verdict == "REJECTED"
    assert verdict_math.rejection_category == "ARITHMETIC_ERROR"

    # 3. Ungrounded Assertion: Reasoning summary fails to cite any triggered risk factor
    bad_grounding_draft = valid_decision.model_copy(
        update={"reasoning_summary": "This transaction looks completely fine with no issues."}
    )
    verdict_grounding = await evaluator.evaluate_assessment(fraudulent_transaction, bad_grounding_draft)
    assert verdict_grounding.verdict == "REJECTED"
    assert verdict_grounding.rejection_category == "UNGROUNDED_ASSERTION"


@pytest.mark.asyncio
async def test_langgraph_actor_critic_retry_and_circuit_breaker(
    fraudulent_transaction: Transaction,
) -> None:
    """Verify LangGraph StateGraph executes Actor-Critic retry loop and Circuit Breaker fallback."""
    # 1. Create a DecisionAgent that fails on attempt 1 (returns wrong score) and self-corrects on retry
    call_counter = {"count": 0}

    class FlakyDecisionAgent(DecisionAgent):
        async def make_decision(self, transaction, data_result=None, analysis_result=None, **kwargs):  # type: ignore[override]
            call_counter["count"] += 1
            real_assessment = await super().make_decision(
                transaction,
                data_result=data_result,
                analysis_result=analysis_result,
                **kwargs,
            )
            if call_counter["count"] == 1:
                # Corrupt the first draft so EvaluatorAgent rejects it
                return real_assessment.model_copy(update={"decision": "APPROVE"})
            return real_assessment

    orch_retry = OrchestratorAgent(
        provider="mock",
        decision_agent=FlakyDecisionAgent(),
        model_config=AgentModelConfig(),
    )
    state_retry = await orch_retry.run_workflow_state(fraudulent_transaction)
    assert call_counter["count"] == 2
    assert state_retry.retry_count == 1
    assert state_retry.evaluator_verdict == "ACCEPTED"
    assert state_retry.is_fallback is False
    final_assessment = FraudAssessment.model_validate(state_retry.draft_assessment)
    assert final_assessment.decision == "DECLINE"

    # 2. Create a DecisionAgent that always fails so the Circuit Breaker trips after max_retries=3
    class AlwaysBrokenDecisionAgent(DecisionAgent):
        async def make_decision(self, transaction, data_result=None, analysis_result=None, **kwargs):  # type: ignore[override]
            real = await super().make_decision(
                transaction,
                data_result=data_result,
                analysis_result=analysis_result,
                **kwargs,
            )
            return real.model_copy(update={"decision": "APPROVE"})

    orch_cb = OrchestratorAgent(
        provider="mock",
        decision_agent=AlwaysBrokenDecisionAgent(),
        max_retries=3,
    )
    state_cb = await orch_cb.run_workflow_state(fraudulent_transaction)
    assert state_cb.is_fallback is True
    assert state_cb.retry_count == 4  # Initial + 3 retries rejected -> Circuit Breaker
    cb_assessment = FraudAssessment.model_validate(state_cb.draft_assessment)
    assert cb_assessment.decision == "DECLINE"
    assert "Circuit Breaker Fallback" in cb_assessment.reasoning_summary


@pytest.mark.asyncio
async def test_langgraph_supplementary_retrieval_subdelegation(
    fraudulent_transaction: Transaction,
) -> None:
    """Verify AnalysisAgent can request supplementary data from DataRetrieverAgent via the Supervisor graph."""
    # Disable initial RAG retrieval so rag_policies starts empty, prompting AnalysisAgent to request supplementary data
    orch_supp = OrchestratorAgent(
        provider="mock",
        agent_flags=AgentFeatureFlags(enable_rag_policy_retrieval=False),
    )
    state_supp = await orch_supp.run_workflow_state(fraudulent_transaction)
    assert state_supp.supplementary_count == 1
    assert len(state_supp.supplementary_retrievals) == 1
    assert state_supp.supplementary_retrievals[0]["tool_invoked"] == "query_fraud_policies_tool"
    assert len(state_supp.supplementary_retrievals[0]["retrieved_policies"]) >= 1


@pytest.mark.asyncio
async def test_orchestrator_agent_feature_flags(fraudulent_transaction: Transaction) -> None:
    """Verify toggling each agent flag on and off controls OrchestratorAgent coordination."""
    # 1. Disable Orchestrator Agent completely
    orch_disabled = OrchestratorAgent(
        provider="mock",
        agent_flags=AgentFeatureFlags(enable_orchestrator_agent=False),
    )
    res_orch_off = await orch_disabled.coordinate_evaluation(fraudulent_transaction)
    assert res_orch_off.decision == "APPROVE"
    assert res_orch_off.overall_risk_score == 0.0
    assert res_orch_off.tools_invoked == []
    assert "enable_orchestrator_agent=False" in res_orch_off.reasoning_summary

    # 2. Disable Data Retriever Agent only
    data_disabled = OrchestratorAgent(
        provider="mock",
        agent_flags=AgentFeatureFlags(enable_data_retriever_agent=False),
    )
    res_data_off = await data_disabled.coordinate_evaluation(fraudulent_transaction)
    assert "lookup_account_history_tool" not in res_data_off.tools_invoked
    assert "query_fraud_policies_tool" not in res_data_off.tools_invoked
    categories = [rf.category for rf in res_data_off.risk_factors]
    assert "ACCOUNT_HISTORY" not in categories
    assert "GEO_ANOMALY" in categories
    assert res_data_off.decision == "DECLINE"

    # 3. Disable Analysis Agent only
    analysis_disabled = OrchestratorAgent(
        provider="mock",
        agent_flags=AgentFeatureFlags(enable_analysis_agent=False),
    )
    res_analysis_off = await analysis_disabled.coordinate_evaluation(fraudulent_transaction)
    assert "lookup_account_history_tool" in res_analysis_off.tools_invoked
    assert "query_fraud_policies_tool" in res_analysis_off.tools_invoked
    categories_analysis_off = [rf.category for rf in res_analysis_off.risk_factors]
    assert categories_analysis_off == ["ACCOUNT_HISTORY"]
    assert res_analysis_off.overall_risk_score == 20.0
    assert res_analysis_off.decision == "APPROVE"

    # 4. Disable Decision Agent only
    decision_disabled = OrchestratorAgent(
        provider="mock",
        agent_flags=AgentFeatureFlags(enable_decision_agent=False),
    )
    res_decision_off = await decision_disabled.coordinate_evaluation(fraudulent_transaction)
    assert res_decision_off.overall_risk_score == 0.0
    assert res_decision_off.decision == "APPROVE"
    assert "enable_decision_agent=False" in res_decision_off.reasoning_summary
    assert len(res_decision_off.tools_invoked) >= 4
