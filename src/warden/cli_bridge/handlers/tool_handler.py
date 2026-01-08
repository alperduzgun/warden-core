"""
Tool Handler for Warden Bridge.
Handles AST provider discovery and validation.
"""

from typing import Any, Dict, List
from warden.shared.infrastructure.logging import get_logger
from warden.cli_bridge.protocol import IPCError, ErrorCode
from warden.cli_bridge.handlers.base import BaseHandler

logger = get_logger(__name__)

class ToolHandler(BaseHandler):
    """Handles discovery and testing of language tools (LSP, AST providers)."""

    async def get_available_providers(self) -> List[Dict[str, Any]]:
        """List all available AST providers and their metadata."""
        try:
            from warden.ast.application.provider_registry import ASTProviderRegistry
            registry = ASTProviderRegistry()
            await registry.discover_providers()

            providers = []
            for metadata in registry.list_providers():
                providers.append({
                    "name": metadata.name,
                    "languages": [lang.value for lang in metadata.supported_languages],
                    "priority": metadata.priority.name,
                    "version": metadata.version,
                    "source": "built-in" if metadata.name in ["Python AST", "Tree-sitter"] else "PyPI",
                })
            return providers
        except Exception as e:
            logger.error("get_available_providers_failed", error=str(e))
            raise IPCError(ErrorCode.INTERNAL_ERROR, f"Failed to get providers: {e}")

    async def test_provider(self, language: str) -> Dict[str, Any]:
        """Test if a language provider is available and functional."""
        try:
            from warden.ast.application.provider_registry import ASTProviderRegistry
            from warden.ast.domain.enums import CodeLanguage
            
            try:
                lang = CodeLanguage(language.lower())
            except ValueError:
                return {
                    "available": False,
                    "error": f"Unknown language: {language}",
                    "supportedLanguages": [l.value for l in CodeLanguage if l != CodeLanguage.UNKNOWN]
                }

            registry = ASTProviderRegistry()
            await registry.discover_providers()
            provider = registry.get_provider(lang)

            if not provider:
                return {"available": False, "language": language}

            is_valid = await provider.validate()
            return {
                "available": True,
                "providerName": provider.metadata.name,
                "priority": provider.metadata.priority.name,
                "version": provider.metadata.version,
                "validated": is_valid,
            }
        except Exception as e:
            logger.error("test_provider_failed", language=language, error=str(e))
            raise IPCError(ErrorCode.INTERNAL_ERROR, f"Provider test failed: {e}")
