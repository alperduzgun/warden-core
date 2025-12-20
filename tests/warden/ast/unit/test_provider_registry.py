"""
Unit tests for ASTProviderRegistry.

Tests provider registration, priority-based selection, and language routing.
"""

import pytest

from warden.ast.application.provider_interface import IASTProvider
from warden.ast.application.provider_registry import ASTProviderRegistry
from warden.ast.domain.models import (
    ASTProviderMetadata,
    ParseResult,
)
from warden.ast.domain.enums import (
    ASTProviderPriority,
    CodeLanguage,
    ParseStatus,
)


# Mock providers for testing
class MockNativeProvider(IASTProvider):
    """Mock native Python provider."""

    def __init__(self) -> None:
        self._metadata = ASTProviderMetadata(
            name="mock-native",
            priority=ASTProviderPriority.NATIVE,
            supported_languages=[CodeLanguage.PYTHON],
        )

    @property
    def metadata(self) -> ASTProviderMetadata:
        return self._metadata

    async def parse(
        self, source_code: str, language: CodeLanguage, file_path: str | None = None
    ) -> ParseResult:
        return ParseResult(
            status=ParseStatus.SUCCESS,
            language=language,
            provider_name=self.metadata.name,
        )

    def supports_language(self, language: CodeLanguage) -> bool:
        return language == CodeLanguage.PYTHON

    async def validate(self) -> bool:
        return True


class MockTreeSitterProvider(IASTProvider):
    """Mock tree-sitter provider."""

    def __init__(self) -> None:
        self._metadata = ASTProviderMetadata(
            name="mock-tree-sitter",
            priority=ASTProviderPriority.TREE_SITTER,
            supported_languages=[CodeLanguage.PYTHON, CodeLanguage.JAVASCRIPT],
        )

    @property
    def metadata(self) -> ASTProviderMetadata:
        return self._metadata

    async def parse(
        self, source_code: str, language: CodeLanguage, file_path: str | None = None
    ) -> ParseResult:
        return ParseResult(
            status=ParseStatus.SUCCESS,
            language=language,
            provider_name=self.metadata.name,
        )

    def supports_language(self, language: CodeLanguage) -> bool:
        return language in [CodeLanguage.PYTHON, CodeLanguage.JAVASCRIPT]

    async def validate(self) -> bool:
        return True


class TestASTProviderRegistry:
    """Test suite for ASTProviderRegistry."""

    def test_registry_initialization(self) -> None:
        """Test registry initializes empty."""
        registry = ASTProviderRegistry()
        assert len(registry) == 0
        assert registry.list_supported_languages() == []

    def test_register_provider(self) -> None:
        """Test provider registration."""
        registry = ASTProviderRegistry()
        provider = MockNativeProvider()

        registry.register(provider)

        assert len(registry) == 1
        assert "mock-native" in registry
        assert CodeLanguage.PYTHON in registry.list_supported_languages()

    def test_register_multiple_providers(self) -> None:
        """Test multiple provider registration."""
        registry = ASTProviderRegistry()
        native_provider = MockNativeProvider()
        tree_sitter_provider = MockTreeSitterProvider()

        registry.register(native_provider)
        registry.register(tree_sitter_provider)

        assert len(registry) == 2
        assert "mock-native" in registry
        assert "mock-tree-sitter" in registry

    def test_priority_based_selection(self) -> None:
        """Test provider selection by priority."""
        registry = ASTProviderRegistry()
        native_provider = MockNativeProvider()
        tree_sitter_provider = MockTreeSitterProvider()

        # Register in reverse priority order
        registry.register(tree_sitter_provider)
        registry.register(native_provider)

        # Should select native provider (higher priority)
        selected = registry.get_provider(CodeLanguage.PYTHON)

        assert selected is not None
        assert selected.metadata.name == "mock-native"
        assert selected.metadata.priority == ASTProviderPriority.NATIVE

    def test_get_provider_for_unsupported_language(self) -> None:
        """Test getting provider for unsupported language."""
        registry = ASTProviderRegistry()
        provider = MockNativeProvider()
        registry.register(provider)

        selected = registry.get_provider(CodeLanguage.JAVA)

        assert selected is None

    def test_get_provider_by_name(self) -> None:
        """Test getting provider by exact name."""
        registry = ASTProviderRegistry()
        provider = MockNativeProvider()
        registry.register(provider)

        found = registry.get_provider_by_name("mock-native")
        assert found is not None
        assert found.metadata.name == "mock-native"

        not_found = registry.get_provider_by_name("nonexistent")
        assert not_found is None

    def test_get_all_providers_for_language(self) -> None:
        """Test getting all providers for a language."""
        registry = ASTProviderRegistry()
        native_provider = MockNativeProvider()
        tree_sitter_provider = MockTreeSitterProvider()

        registry.register(native_provider)
        registry.register(tree_sitter_provider)

        providers = registry.get_all_providers(CodeLanguage.PYTHON)

        assert len(providers) == 2
        # Should be sorted by priority (native first)
        assert providers[0].metadata.name == "mock-native"
        assert providers[1].metadata.name == "mock-tree-sitter"

    def test_unregister_provider(self) -> None:
        """Test provider unregistration."""
        registry = ASTProviderRegistry()
        provider = MockNativeProvider()
        registry.register(provider)

        assert "mock-native" in registry

        success = registry.unregister("mock-native")

        assert success is True
        assert "mock-native" not in registry
        assert len(registry) == 0

    def test_unregister_nonexistent_provider(self) -> None:
        """Test unregistering nonexistent provider."""
        registry = ASTProviderRegistry()

        success = registry.unregister("nonexistent")

        assert success is False

    def test_clear_registry(self) -> None:
        """Test clearing all providers."""
        registry = ASTProviderRegistry()
        registry.register(MockNativeProvider())
        registry.register(MockTreeSitterProvider())

        assert len(registry) == 2

        registry.clear()

        assert len(registry) == 0
        assert registry.list_supported_languages() == []

    def test_list_providers(self) -> None:
        """Test listing all providers."""
        registry = ASTProviderRegistry()
        registry.register(MockNativeProvider())
        registry.register(MockTreeSitterProvider())

        providers = registry.list_providers()

        assert len(providers) == 2
        names = {p.name for p in providers}
        assert "mock-native" in names
        assert "mock-tree-sitter" in names

    def test_preferred_priority_selection(self) -> None:
        """Test provider selection with preferred priority."""
        registry = ASTProviderRegistry()
        native_provider = MockNativeProvider()
        tree_sitter_provider = MockTreeSitterProvider()

        registry.register(native_provider)
        registry.register(tree_sitter_provider)

        # Request tree-sitter specifically
        selected = registry.get_provider(
            CodeLanguage.PYTHON, preferred_priority=ASTProviderPriority.TREE_SITTER
        )

        assert selected is not None
        assert selected.metadata.name == "mock-tree-sitter"

    def test_provider_overwrite_warning(self) -> None:
        """Test registering provider with duplicate name."""
        registry = ASTProviderRegistry()
        provider1 = MockNativeProvider()
        provider2 = MockNativeProvider()

        registry.register(provider1)
        registry.register(provider2)  # Should overwrite

        assert len(registry) == 1
        assert "mock-native" in registry
