"""Secret application layer - manager and resolver."""

from .secret_manager import SecretManager, get_secret
from .template_resolver import TemplateResolver

__all__ = ["SecretManager", "get_secret", "TemplateResolver"]
