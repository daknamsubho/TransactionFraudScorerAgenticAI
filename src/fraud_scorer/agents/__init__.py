"""Modular LangChain Multi-Agent System for Transaction Fraud Scoring."""

from fraud_scorer.agents.analysis_agent import AnalysisAgent, AnalysisResult
from fraud_scorer.agents.data_retriever_agent import DataRetrievalResult, DataRetrieverAgent
from fraud_scorer.agents.decision_agent import DecisionAgent
from fraud_scorer.agents.orchestrator_agent import (
    FraudScorerOrchestrator,
    OrchestratorAgent,
    check_ollama_connection,
    display_assessment,
    is_ollama_available,
    main,
    run_demo,
)
from fraud_scorer.agents.prompts import (
    FRAUD_ANALYST_SYSTEM_PROMPT,
    TRANSACTION_EVALUATION_TEMPLATE,
    get_fraud_chat_prompt_template,
)
from fraud_scorer.agents.tools import (
    check_geo_anomaly_tool,
    check_merchant_risk_tool,
    check_velocity_tool,
    configure_langchain_with_mcp_tools,
    get_langchain_fraud_tools,
    lookup_account_history_tool,
)

__all__ = [
    "AnalysisAgent",
    "AnalysisResult",
    "DataRetrievalResult",
    "DataRetrieverAgent",
    "DecisionAgent",
    "FRAUD_ANALYST_SYSTEM_PROMPT",
    "FraudScorerOrchestrator",
    "OrchestratorAgent",
    "TRANSACTION_EVALUATION_TEMPLATE",
    "check_geo_anomaly_tool",
    "check_merchant_risk_tool",
    "check_ollama_connection",
    "check_velocity_tool",
    "configure_langchain_with_mcp_tools",
    "display_assessment",
    "get_fraud_chat_prompt_template",
    "get_langchain_fraud_tools",
    "is_ollama_available",
    "lookup_account_history_tool",
    "main",
    "run_demo",
]
