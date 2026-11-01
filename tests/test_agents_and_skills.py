"""Unit and integration tests for individual LangChain Agents, Skills, and AgentFeatureFlags (PRD-009)."""

import pytest

from fraud_scorer.agents.analysis_agent import AnalysisAgent
from fraud_scorer.agents.data_retriever_agent import DataRetrieverAgent
from fraud_scorer.agents.decision_agent import DecisionAgent
from fraud_scorer.agents.orchestrator_agent import OrchestratorAgent
from fraud_scorer.config import AgentFeatureFlags
from fraud_scorer.models.transaction import Transaction
from fraud_scorer.skills.account_history_skill import AccountHistorySkill
from fraud_scorer.skills.amount_anomaly_skill import AmountAnomalySkill
from fraud_scorer.skills.geo_anomaly_skill import GeoAnomalySkill
from fraud_scorer.skills.merchant_risk_skill import MerchantRiskSkill
from fraud_scorer.skills.risk_scoring_decision_skill import RiskScoringDecisionSkill
from fraud_scorer.skills.velocity_analysis_skill import VelocityAnalysisSkill


@pytest.mark.asyncio
async def test_individual_skills(
    normal_transaction: Transaction,
    fraudulent_transaction: Transaction,
) -> None:
    """Verify each of the 6 separate skill files executes and returns structured evidence."""
    # 1. AccountHistorySkill
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

    # 2. VelocityAnalysisSkill
    vel_skill = VelocityAnalysisSkill()
    assert vel_skill.get_langchain_tool().name == "check_velocity_tool"
    _, susp_vel_factors, _ = await vel_skill.execute(fraudulent_transaction.account_id, 60)
    assert len(susp_vel_factors) == 1
    assert susp_vel_factors[0].category == "VELOCITY"

    # 3. GeoAnomalySkill
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

    # 4. MerchantRiskSkill
    merch_skill = MerchantRiskSkill()
    assert merch_skill.get_langchain_tool().name == "check_merchant_risk_tool"
    _, susp_merch_factors, _ = await merch_skill.execute(
        merchant_id=fraudulent_transaction.merchant.merchant_id,
        mcc=fraudulent_transaction.merchant.mcc,
    )
    assert len(susp_merch_factors) == 1
    assert susp_merch_factors[0].category == "MERCHANT_RISK"

    # 5. AmountAnomalySkill
    amt_skill = AmountAnomalySkill()
    amt_factors = amt_skill.execute(fraudulent_transaction, susp_hist)
    assert len(amt_factors) == 1
    assert amt_factors[0].category == "AMOUNT_ANOMALY"

    # 6. RiskScoringDecisionSkill
    dec_skill = RiskScoringDecisionSkill()
    all_factors = [*susp_acc_factors, *susp_vel_factors, *susp_geo_factors, *susp_merch_factors, *amt_factors]
    assessment = dec_skill.execute(
        transaction=fraudulent_transaction,
        risk_factors=all_factors,
        tools_invoked=["lookup_account_history_tool", "check_velocity_tool"],
    )
    assert assessment.decision == "DECLINE"
    assert assessment.overall_risk_score >= 70.0


@pytest.mark.asyncio
async def test_individual_agents_pipeline(
    normal_transaction: Transaction,
    fraudulent_transaction: Transaction,
) -> None:
    """Verify DataRetrieverAgent, AnalysisAgent, and DecisionAgent operate independently."""
    retriever = DataRetrieverAgent()
    analyzer = AnalysisAgent()
    decider = DecisionAgent()

    # Normal flow
    data_res = await retriever.retrieve_data(normal_transaction, use_llm=False)
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
    assert res_analysis_off.tools_invoked == ["lookup_account_history_tool"]
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
    assert len(res_decision_off.tools_invoked) == 4
