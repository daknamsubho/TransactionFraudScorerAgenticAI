"""Configuration management for Transaction Fraud Scorer Agentic AI."""

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


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
