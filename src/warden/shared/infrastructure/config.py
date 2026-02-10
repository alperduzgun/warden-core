"""
Application configuration using Pydantic Settings.

Loads configuration from environment variables and .env file.
"""

import secrets
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List
import structlog


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
    debug: bool = Field(default=False, description="Debug mode")
    log_level: str = Field(default="INFO", description="Logging level")

    # API Server
    api_host: str = Field(default="127.0.0.1", description="API host")
    api_port: int = Field(default=8000, description="API port")
    api_workers: int = Field(default=4, description="Number of workers")
    api_reload: bool = Field(default=True, description="Auto-reload on code changes")

    # CORS
    cors_origins: List[str] = Field(
        default=[],
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
        default="",
        description="Secret key for JWT signing",
    )
    algorithm: str = Field(default="HS256", description="JWT algorithm")
    access_token_expire_minutes: int = Field(
        default=30,
        description="Access token expiration in minutes",
    )

    # Logging / Privacy
    log_redaction_enabled: bool = Field(default=True, description="Enable PII redaction in logs")

    @property
    def is_development(self) -> bool:
        """Check if running in development mode."""
        return self.app_env.lower() == "development"

    @property
    def is_production(self) -> bool:
        """Check if running in production mode."""
        return self.app_env.lower() == "production"

    @model_validator(mode="after")
    def _validate_production_settings(self) -> "Settings":
        """Fail fast: enforce critical settings in production."""
        logger = structlog.get_logger(__name__)

        if not self.secret_key:
            if self.is_production:
                raise ValueError(
                    "SECRET_KEY must be set in production. "
                    "Set the SECRET_KEY environment variable to a strong random value."
                )
            else:
                # Auto-generate in dev mode with loud warning
                self.secret_key = secrets.token_urlsafe(32)
                logger.warning(
                    "auto_generated_secret_key",
                    message="SECRET_KEY was empty. Auto-generated a random key for development. "
                           "Set SECRET_KEY in .env for production use.",
                    key_length=len(self.secret_key)
                )
        return self


# Global settings instance
settings = Settings()
