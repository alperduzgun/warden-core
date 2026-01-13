"""
Application configuration using Pydantic Settings.

Loads configuration from environment variables and .env file.
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List


class Settings(BaseSettings):
    """Application settings loaded from environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = Field(default="warden-core", description="Application name")
    app_env: str = Field(default="development", description="Environment (development/production)")
    debug: bool = Field(default=True, description="Debug mode")
    log_level: str = Field(default="INFO", description="Logging level")

    # API Server
    api_host: str = Field(default="0.0.0.0", description="API host")
    api_port: int = Field(default=8000, description="API port")
    api_workers: int = Field(default=4, description="Number of workers")
    api_reload: bool = Field(default=True, description="Auto-reload on code changes")

    # CORS
    cors_origins: List[str] = Field(
        default=["http://localhost:5173", "http://localhost:3000"],
        description="Allowed CORS origins",
    )

    # ChromaDB Vector Database
    chroma_path: str = Field(
        default=".warden/embeddings",
        description="ChromaDB persistent storage path",
    )
    chroma_collection: str = Field(
        default="warden_codebase",
        description="ChromaDB collection name",
    )

    # OpenAI (for embeddings)
    openai_api_key: str | None = Field(default=None, description="OpenAI API key")
    openai_embedding_model: str = Field(
        default="text-embedding-3-small",
        description="OpenAI embedding model",
    )

    # Azure OpenAI (alternative)
    azure_openai_endpoint: str | None = Field(
        default=None,
        description="Azure OpenAI endpoint",
    )
    azure_openai_api_key: str | None = Field(
        default=None,
        description="Azure OpenAI API key",
    )
    azure_openai_embedding_deployment: str = Field(
        default="text-embedding-3-small",
        description="Azure embedding deployment name",
    )

    # LLM Provider
    llm_provider: str = Field(
        default="deepseek",
        description="LLM provider (deepseek/openai/groq/anthropic)",
    )
    deepseek_api_key: str | None = Field(default=None, description="DeepSeek API key")
    deepseek_model: str = Field(default="deepseek-chat", description="DeepSeek model")

    # File Storage
    warden_dir: str = Field(default=".warden", description="Warden directory")
    issues_file: str = Field(
        default=".warden/issues.json",
        description="Issues JSON file path",
    )
    reports_dir: str = Field(
        default=".warden/reports",
        description="Reports directory",
    )

    # Security
    secret_key: str = Field(
        default="change-this-in-production",
        description="Secret key for JWT signing",
    )
    algorithm: str = Field(default="HS256", description="JWT algorithm")
    access_token_expire_minutes: int = Field(
        default=30,
        description="Access token expiration in minutes",
    )

    @property
    def is_development(self) -> bool:
        """Check if running in development mode."""
        return self.app_env.lower() == "development"

    @property
    def is_production(self) -> bool:
        """Check if running in production mode."""
        return self.app_env.lower() == "production"


# Global settings instance
settings = Settings()
