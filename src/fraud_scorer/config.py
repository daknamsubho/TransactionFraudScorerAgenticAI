"""Configuration management for Transaction Fraud Scorer Agentic AI."""

import os
from functools import lru_cache
from typing import Literal

import httpx
from pydantic import AliasChoices, BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentFeatureFlags(BaseModel):
    """Configurable boolean flags to enable or disable individual agents."""

    enable_orchestrator_agent: bool = Field(
        default=True,
        description="Enable or disable the top-level Orchestrator manager agent.",
    )
    enable_data_retriever_agent: bool = Field(
        default=True,
        description="Enable or disable the Data Retriever Agent (account history & RAG policy lookup).",
    )
    enable_analysis_agent: bool = Field(
        default=True,
        description="Enable or disable the Analysis Agent (velocity, geo, merchant, and amount analysis).",
    )
    enable_decision_agent: bool = Field(
        default=True,
        description="Enable or disable the Decision Agent (final risk score and APPROVE/REVIEW/DECLINE disposition).",
    )
    enable_evaluator_agent: bool = Field(
        default=True,
        description="Enable or disable the Evaluator Agent (Actor-Critic mathematical & policy compliance auditor).",
    )
    enable_rag_policy_retrieval: bool = Field(
        default=True,
        description="Enable or disable ChromaDB RAG policy retrieval in DataRetrieverAgent.",
    )


class AgentModelConfig(BaseModel):
    """Configuration mapping distinct model tiers to specific agent roles (Heterogeneous Model Tiering)."""

    # Tier 1: Fast Small Language Models (Tool-calling & JSON schema formatting)
    data_retrieval_model: str = Field(
        default="llama3.2:3b",
        description="Tier 1 Fast SLM for Data Retrieval Agent (SQLite & ChromaDB tool calling).",
    )

    # Tier 2: Mid-sized Analytical Models (Numerical correlation & signal weighting)
    analysis_model: str = Field(
        default="llama3.1:8b",
        description="Tier 2 Balanced Analytical LLM for Analysis Agent.",
    )
    governance_model: str = Field(
        default="llama3.1:8b",
        description="Tier 2 Compliance Policy LLM.",
    )

    # Tier 3: Reasoning and Critical Auditor Models (Llama 3.1 8B, PRD-019)
    decision_model: str = Field(
        default="llama3.1:8b",
        description="Tier 3 Reasoning model (Llama 3.1 8B) for Decision Agent (Actor).",
    )
    evaluator_model: str = Field(
        default="llama3.1:8b",
        description="Tier 3 Critical Auditor model (Llama 3.1 8B) for Evaluator Agent (Critic).",
    )


@lru_cache(maxsize=32)
def get_installed_ollama_models(base_url: str) -> tuple[str, ...]:
    """Fetch and cache the list of installed model tags from the local Ollama server."""
    try:
        resp = httpx.get(f"{base_url.rstrip('/')}/api/tags", timeout=1.5)
        if resp.status_code == 200:
            data = resp.json()
            models = data.get("models") or []
            return tuple(str(m.get("name", "")) for m in models if m.get("name"))
    except Exception:
        pass
    return ()


def resolve_ollama_model(
    preferred_model: str,
    fallback_model: str = "llama3.2:3b",
    base_url: str = "http://localhost:11434",
) -> str:
    """Resolve an agent's preferred tier model against locally installed Ollama models.

    If `preferred_model` (e.g. `llama3.1:8b` or `llama3.2:3b`) is installed in Ollama,
    returns `preferred_model`. Otherwise gracefully falls back to `fallback_model`
    (e.g. `llama3.2:3b`) so local/Colab execution never fails with a 404 model error.
    """
    installed = get_installed_ollama_models(base_url)
    if not installed:
        return preferred_model
    preferred_base = preferred_model.split(":")[0]
    for tag in installed:
        if tag == preferred_model or tag.split(":")[0] == preferred_base:
            return preferred_model
    return fallback_model


class Settings(BaseSettings):
    """Application and environment configuration."""

    # Local Ollama Settings
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2:3b"
    default_llm_provider: Literal["ollama", "mock", "gemini", "anthropic", "openai"] = "ollama"

    # Heterogeneous Model Tiering Defaults (PRD-017 & PRD-019)
    data_retrieval_model: str = "llama3.2:3b"
    analysis_model: str = "llama3.1:8b"
    decision_model: str = "llama3.1:8b"
    evaluator_model: str = "llama3.1:8b"

    # Optional Cloud LLM Keys (fallback or comparison)
    gemini_api_key: str | None = None
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None

    # MCP Server Settings
    mcp_server_transport: Literal["stdio", "sse"] = "stdio"
    mcp_server_host: str = "127.0.0.1"
    mcp_server_port: int = 8000

    # API Gateway Settings
    api_gateway_host: str = "0.0.0.0"
    api_gateway_port: int = 8000
    enable_cloudflare_tunnel: bool = False

    # SQLite RDBMS & ChromaDB Policy Settings
    sqlite_db_path: str = "src/sqllite/fraud_scorer.db"
    default_policy_year: str = "2026"

    # Actor-Critic Loop & SLA Circuit Breaker Controls (PRD-017)
    max_evaluation_retries: int = 3
    max_evaluation_timeout_ms: float = 1800.0

    # Configurable Agent Feature Flags (PRD-009 & PRD-017)
    enable_orchestrator_agent: bool = True
    enable_data_retriever_agent: bool = True
    enable_analysis_agent: bool = True
    enable_decision_agent: bool = True
    enable_evaluator_agent: bool = True
    enable_rag_policy_retrieval: bool = True

    # LangSmith & OpenTelemetry Observability Settings (PRD-018)
    langsmith_tracing: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2", "LANGCHAIN_TRACING", "langsmith_tracing"
        ),
    )
    langsmith_endpoint: str = Field(
        default="https://api.smith.langchain.com",
        validation_alias=AliasChoices("LANGSMITH_ENDPOINT", "LANGCHAIN_ENDPOINT", "langsmith_endpoint"),
    )
    langsmith_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("LANGSMITH_API_KEY", "LANGCHAIN_API_KEY", "langsmith_api_key"),
    )
    langsmith_project: str = Field(
        default="fraud-scorer-agentic-ai",
        validation_alias=AliasChoices("LANGSMITH_PROJECT", "LANGCHAIN_PROJECT", "langsmith_project"),
    )
    langsmith_mask_pii: bool = True
    langsmith_sample_rate: float = 1.0
    otel_exporter_otlp_endpoint: str | None = None
    enable_websocket_trace_streaming: bool = True

    # General App Settings
    log_level: str = "INFO"
    environment: Literal["development", "staging", "production"] = "development"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def is_langsmith_enabled(self) -> bool:
        """Return True only when LangSmith tracing is enabled and a non-empty API key is present."""
        return bool(self.langsmith_tracing and self.langsmith_api_key and self.langsmith_api_key.strip())

    def get_agent_flags(self) -> AgentFeatureFlags:
        """Return an AgentFeatureFlags instance populated from current settings."""
        return AgentFeatureFlags(
            enable_orchestrator_agent=self.enable_orchestrator_agent,
            enable_data_retriever_agent=self.enable_data_retriever_agent,
            enable_analysis_agent=self.enable_analysis_agent,
            enable_decision_agent=self.enable_decision_agent,
            enable_evaluator_agent=self.enable_evaluator_agent,
            enable_rag_policy_retrieval=self.enable_rag_policy_retrieval,
        )

    def get_model_config(self) -> AgentModelConfig:
        """Return an AgentModelConfig instance populated from current settings."""
        return AgentModelConfig(
            data_retrieval_model=self.data_retrieval_model,
            analysis_model=self.analysis_model,
            decision_model=self.decision_model,
            evaluator_model=self.evaluator_model,
        )


def load_colab_secrets(override: bool = False) -> dict[str, str]:
    """Import secrets from google.colab.userdata if executing in Google Colab.

    Populates matching environment variables (e.g. LANGSMITH_API_KEY, GEMINI_API_KEY)
    so Settings and downstream client SDKs pick them up seamlessly.
    """
    imported: dict[str, str] = {}
    try:
        from google.colab import userdata  # type: ignore[import-not-found]

        candidate_keys = (
            "LANGSMITH_API_KEY",
            "LANGCHAIN_API_KEY",
            "LANGSMITH_PROJECT",
            "LANGSMITH_TRACING",
            "LANGSMITH_ENDPOINT",
            "GEMINI_API_KEY",
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
        )
        for key in candidate_keys:
            try:
                val = userdata.get(key)
                if val:
                    val_str = str(val).strip()
                    if val_str and (override or key not in os.environ or not os.environ[key]):
                        os.environ[key] = val_str
                        imported[key] = val_str
            except Exception:
                pass

        has_key = "LANGSMITH_API_KEY" in os.environ or "LANGCHAIN_API_KEY" in os.environ
        tracing_val = os.environ.get("LANGSMITH_TRACING", "").lower()
        if has_key and tracing_val != "false":
            os.environ["LANGSMITH_TRACING"] = "true"
            os.environ["LANGCHAIN_TRACING_V2"] = "true"
    except (ImportError, ModuleNotFoundError, Exception):
        pass

    return imported


# Load secrets if running in Google Colab prior to Settings initialization
load_colab_secrets()

# Global singleton instance
settings = Settings()
