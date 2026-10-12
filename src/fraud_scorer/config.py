"""Configuration management for Transaction Fraud Scorer Agentic AI."""

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application and environment configuration."""

    # LLM Settings
    gemini_api_key: str | None = None
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    default_llm_provider: Literal["mock", "gemini", "anthropic", "openai"] = "mock"

    # MCP Server Settings
    mcp_server_transport: Literal["stdio", "sse"] = "stdio"
    mcp_server_host: str = "127.0.0.1"
    mcp_server_port: int = 8000

    # General App Settings
    log_level: str = "INFO"
    environment: Literal["development", "staging", "production"] = "development"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


# Global singleton instance
settings = Settings()
