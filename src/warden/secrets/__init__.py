"""Warden Secrets Module.

Multi-source secret loading with chain of responsibility pattern.

Supports:
- Environment variables (including GitHub Actions secrets)
- .env files (local development)
- Azure Key Vault (production)

Auto-Detection:
- If AZURE_KEY_VAULT_URL is set -> Azure Key Vault (priority 0)
- If GITHUB_ACTIONS=true -> Env vars only
- Otherwise -> .env first, then env vars

Usage:
    # Using manager directly
    from warden.secrets import SecretManager

    manager = SecretManager()
    result = await manager.get_secret("AZURE_OPENAI_API_KEY")
    if result.found:
        print(f"Value from {result.source.value}")

    # Convenience function
    from warden.secrets import get_secret

    api_key = await get_secret("AZURE_OPENAI_API_KEY")

    # Template resolution for config.yaml
    from warden.secrets import TemplateResolver

    resolver = TemplateResolver()
    resolved_config = await resolver.resolve(raw_config)
"""

from .application.secret_manager import SecretManager, get_manager, get_secret
from .application.template_resolver import TemplateResolver
from .domain.enums import SecretSource
from .domain.models import SecretProviderConfig, SecretValue
from .providers.base import ISecretProvider

__all__ = [
    # Main classes
    "SecretManager",
    "TemplateResolver",
    # Convenience functions
    "get_secret",
    "get_manager",
    # Domain models
    "SecretValue",
    "SecretSource",
    "SecretProviderConfig",
    # Provider interface
    "ISecretProvider",
]
