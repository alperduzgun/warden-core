"""
AST Provider Registry.

Manages registration and selection of AST providers with priority-based routing.
"""

from typing import Dict, List, Optional
import structlog

from warden.ast.application.provider_interface import IASTProvider
from warden.ast.domain.enums import CodeLanguage, ASTProviderPriority
from warden.ast.domain.models import ASTProviderMetadata

logger = structlog.get_logger(__name__)


class ASTProviderRegistry:
    """
    Registry for AST providers with priority-based selection.

    Manages provider registration and automatically selects the best provider
    for each language based on priority (lower value = higher priority).

    Priority order:
        1. NATIVE - Language-specific native parsers (e.g., Python ast)
        2. SPECIALIZED - Specialized third-party parsers
        3. TREE_SITTER - Universal tree-sitter parser
        4. COMMUNITY - Community-contributed providers
        5. FALLBACK - Basic fallback parsers

    Example usage:
        registry = ASTProviderRegistry()
        registry.register(PythonASTProvider())  # Priority: NATIVE (1)
        registry.register(TreeSitterProvider())  # Priority: TREE_SITTER (3)

        provider = registry.get_provider(CodeLanguage.PYTHON)
        # Returns PythonASTProvider (higher priority)
    """

    def __init__(self) -> None:
        """Initialize empty registry."""
        self._providers: Dict[str, IASTProvider] = {}
        self._language_providers: Dict[CodeLanguage, List[IASTProvider]] = {}

    def register(self, provider: IASTProvider) -> None:
        """
        Register an AST provider.

        Args:
            provider: Provider instance to register

        Raises:
            ValueError: If provider with same name already registered
        """
        metadata = provider.metadata
        provider_name = metadata.name

        if provider_name in self._providers:
            logger.warning(
                "provider_already_registered",
                provider_name=provider_name,
                action="overwriting",
            )

        self._providers[provider_name] = provider

        # Index by supported languages
        for language in metadata.supported_languages:
            if language not in self._language_providers:
                self._language_providers[language] = []

            # Avoid duplicates
            existing_names = {p.metadata.name for p in self._language_providers[language]}
            if provider_name not in existing_names:
                self._language_providers[language].append(provider)

                # Sort by priority (lower value first)
                self._language_providers[language].sort(
                    key=lambda p: p.get_priority(language)
                )

        logger.info(
            "provider_registered",
            provider_name=provider_name,
            priority=metadata.priority.value,
            languages=[lang.value for lang in metadata.supported_languages],
        )

    def unregister(self, provider_name: str) -> bool:
        """
        Unregister a provider by name.

        Args:
            provider_name: Name of provider to unregister

        Returns:
            True if provider was unregistered, False if not found
        """
        if provider_name not in self._providers:
            return False

        provider = self._providers.pop(provider_name)

        # Remove from language indexes
        for language in provider.metadata.supported_languages:
            if language in self._language_providers:
                self._language_providers[language] = [
                    p for p in self._language_providers[language] if p.metadata.name != provider_name
                ]

        logger.info("provider_unregistered", provider_name=provider_name)
        return True

    def get_provider(
        self,
        language: CodeLanguage,
        preferred_priority: Optional[ASTProviderPriority] = None,
    ) -> Optional[IASTProvider]:
        """
        Get best provider for a language.

        Selects provider with highest priority (lowest value).
        If preferred_priority is specified, tries to find provider with that priority.

        Args:
            language: Language to get provider for
            preferred_priority: Optional preferred priority level

        Returns:
            Best provider for language, or None if no provider supports it
        """
        providers = self._language_providers.get(language, [])

        if not providers:
            logger.warning("no_provider_for_language", language=language.value)
            return None

        # If preferred priority specified, try to find it
        if preferred_priority is not None:
            for provider in providers:
                if provider.metadata.priority == preferred_priority:
                    logger.debug(
                        "provider_selected",
                        provider_name=provider.metadata.name,
                        language=language.value,
                        priority=preferred_priority.value,
                        selection="preferred",
                    )
                    return provider

        # Return highest priority (first in sorted list)
        selected = providers[0]
        logger.debug(
            "provider_selected",
            provider_name=selected.metadata.name,
            language=language.value,
            priority=selected.metadata.priority.value,
            selection="auto",
        )
        return selected

    def get_all_providers(self, language: CodeLanguage) -> List[IASTProvider]:
        """
        Get all providers for a language, sorted by priority.

        Args:
            language: Language to get providers for

        Returns:
            List of providers sorted by priority (highest first)
        """
        return self._language_providers.get(language, []).copy()

    def list_providers(self) -> List[ASTProviderMetadata]:
        """
        List all registered providers.

        Returns:
            List of provider metadata
        """
        return [provider.metadata for provider in self._providers.values()]

    def list_supported_languages(self) -> List[CodeLanguage]:
        """
        List all supported languages.

        Returns:
            List of languages with at least one registered provider
        """
        return list(self._language_providers.keys())

    def get_provider_by_name(self, provider_name: str) -> Optional[IASTProvider]:
        """
        Get provider by exact name.

        Args:
            provider_name: Name of provider to retrieve

        Returns:
            Provider if found, None otherwise
        """
        return self._providers.get(provider_name)

    def clear(self) -> None:
        """Clear all registered providers."""
        self._providers.clear()
        self._language_providers.clear()
        logger.info("registry_cleared")

    async def discover_providers(self) -> None:
        """
        Discover and load providers from all sources.

        This is a convenience method that uses ASTProviderLoader to:
        1. Load built-in providers
        2. Discover PyPI entry points
        3. Load local plugins
        4. Load environment-specified providers
        """
        from warden.ast.application.provider_loader import ASTProviderLoader

        loader = ASTProviderLoader(self)
        await loader.load_all()

    def __len__(self) -> int:
        """Get number of registered providers."""
        return len(self._providers)

    def __contains__(self, provider_name: str) -> bool:
        """Check if provider is registered."""
        return provider_name in self._providers
