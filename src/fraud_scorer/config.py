"""Configuration management for Transaction Fraud Scorer Agentic AI."""

from typing import Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentFeatureFlags(BaseModel):
    """Configurable boolean flags to enable or disable individual agents."""

    enable_orchestrator_agent: bool = Field(
        default=True,
        description="Enable or disable the top-level Orchestrator manager agent.",
    )
    enable_data_retriever_agent: bool = Field(
        default=True,
        description="Enable or disable the Data Retriever Agent (account history & profile lookup).",
    )
    enable_analysis_agent: bool = Field(
        default=True,
        description="Enable or disable the Analysis Agent (velocity, geo, merchant, and amount analysis).",
    )
    enable_decision_agent: bool = Field(
        default=True,
        description="Enable or disable the Decision Agent (final risk score and APPROVE/REVIEW/DECLINE disposition).",
    )


class Settings(BaseSettings):
    """Application and environment configuration."""

    # Local Ollama Settings
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2:3b"
    default_llm_provider: Literal["ollama", "mock", "gemini", "anthropic", "openai"] = "ollama"

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

    # SQLite RDBMS Settings
    sqlite_db_path: str = "src/sqllite/fraud_scorer.db"

    # Configurable Agent Feature Flags (PRD-009)
    enable_orchestrator_agent: bool = True
    enable_data_retriever_agent: bool = True
    enable_analysis_agent: bool = True
    enable_decision_agent: bool = True

    # General App Settings
    log_level: str = "INFO"
    environment: Literal["development", "staging", "production"] = "development"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def get_agent_flags(self) -> AgentFeatureFlags:
        """Return an AgentFeatureFlags instance populated from current settings."""
        return AgentFeatureFlags(
            enable_orchestrator_agent=self.enable_orchestrator_agent,
            enable_data_retriever_agent=self.enable_data_retriever_agent,
            enable_analysis_agent=self.enable_analysis_agent,
            enable_decision_agent=self.enable_decision_agent,
        )


# Global singleton instance
settings = Settings()
