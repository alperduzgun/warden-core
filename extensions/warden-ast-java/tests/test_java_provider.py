"""
Tests for JavaParserProvider.

Basic unit tests for provider metadata, language support, and validation.
"""

import pytest
from warden_ast_java.provider import JavaParserProvider
from warden.ast.domain.enums import (
    CodeLanguage,
    ASTProviderPriority,
    ParseStatus,
)


class TestJavaParserProvider:
    """Test suite for JavaParserProvider."""

    @pytest.fixture
    def provider(self) -> JavaParserProvider:
        """Create provider instance."""
        return JavaParserProvider()

    def test_metadata_name(self, provider: JavaParserProvider) -> None:
        """Test provider name is correct."""
        metadata = provider.metadata
        assert metadata.name == "JavaParser"

    def test_metadata_version(self, provider: JavaParserProvider) -> None:
        """Test provider version is set."""
        metadata = provider.metadata
        assert metadata.version == "0.1.0"

    def test_metadata_priority(self, provider: JavaParserProvider) -> None:
        """Test provider has NATIVE priority."""
        metadata = provider.metadata
        assert metadata.priority == ASTProviderPriority.NATIVE

    def test_metadata_supported_languages(self, provider: JavaParserProvider) -> None:
        """Test provider supports Java."""
        metadata = provider.metadata
        assert CodeLanguage.JAVA in metadata.supported_languages
        assert len(metadata.supported_languages) == 1

    def test_supports_java(self, provider: JavaParserProvider) -> None:
        """Test provider supports Java language."""
        assert provider.supports_language(CodeLanguage.JAVA) is True

    def test_does_not_support_python(self, provider: JavaParserProvider) -> None:
        """Test provider does not support Python."""
        assert provider.supports_language(CodeLanguage.PYTHON) is False

    def test_does_not_support_typescript(self, provider: JavaParserProvider) -> None:
        """Test provider does not support TypeScript."""
        assert provider.supports_language(CodeLanguage.TYPESCRIPT) is False

    @pytest.mark.asyncio
    async def test_validate_checks_jpype(self, provider: JavaParserProvider) -> None:
        """Test validate checks for JPype1 availability."""
        result = await provider.validate()
        # Result depends on whether jpype1 is installed
        assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_parse_rejects_empty_code(self, provider: JavaParserProvider) -> None:
        """Test parse rejects empty source code."""
        result = await provider.parse("", CodeLanguage.JAVA)

        assert result.status == ParseStatus.FAILED
        assert len(result.errors) > 0
        assert "empty" in result.errors[0].message.lower()

    @pytest.mark.asyncio
    async def test_parse_rejects_unsupported_language(
        self, provider: JavaParserProvider
    ) -> None:
        """Test parse rejects unsupported languages."""
        result = await provider.parse(
            "print('hello')",
            CodeLanguage.PYTHON,
        )

        assert result.status == ParseStatus.UNSUPPORTED
        assert len(result.errors) > 0
        assert "not support" in result.errors[0].message.lower()

    @pytest.mark.asyncio
    async def test_parse_returns_not_implemented_warning(
        self, provider: JavaParserProvider
    ) -> None:
        """Test parse returns not implemented warning (skeleton)."""
        java_code = """
        public class HelloWorld {
            public static void main(String[] args) {
                System.out.println("Hello, World!");
            }
        }
        """

        result = await provider.parse(java_code, CodeLanguage.JAVA)

        # Skeleton implementation returns FAILED with warning
        assert result.status == ParseStatus.FAILED
        assert len(result.errors) > 0
        assert "not fully implemented" in result.errors[0].message.lower()

    @pytest.mark.asyncio
    async def test_cleanup_safe_when_jvm_not_started(
        self, provider: JavaParserProvider
    ) -> None:
        """Test cleanup is safe when JVM was never started."""
        # Should not raise exception
        await provider.cleanup()

    def test_provider_has_description(self, provider: JavaParserProvider) -> None:
        """Test provider has description."""
        metadata = provider.metadata
        assert len(metadata.description) > 0
        assert "java" in metadata.description.lower()

    def test_provider_requires_installation(self, provider: JavaParserProvider) -> None:
        """Test provider indicates it requires installation."""
        metadata = provider.metadata
        assert metadata.requires_installation is True
        assert metadata.installation_command is not None

    def test_get_priority_returns_native(self, provider: JavaParserProvider) -> None:
        """Test get_priority returns NATIVE priority value."""
        priority = provider.get_priority(CodeLanguage.JAVA)
        assert priority == ASTProviderPriority.NATIVE.value


class TestJavaParserProviderIntegration:
    """Integration tests for JavaParserProvider (requires jpype1)."""

    @pytest.fixture
    def provider(self) -> JavaParserProvider:
        """Create provider instance."""
        return JavaParserProvider()

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        "jpype" not in __import__("sys").modules,
        reason="jpype1 not installed",
    )
    async def test_validate_succeeds_with_jpype_installed(
        self, provider: JavaParserProvider
    ) -> None:
        """Test validate succeeds when jpype1 is installed."""
        result = await provider.validate()
        assert result is True


# Parametrized tests for language support

@pytest.mark.parametrize(
    "language,expected",
    [
        (CodeLanguage.JAVA, True),
        (CodeLanguage.PYTHON, False),
        (CodeLanguage.TYPESCRIPT, False),
        (CodeLanguage.JAVASCRIPT, False),
        (CodeLanguage.CSHARP, False),
        (CodeLanguage.GO, False),
        (CodeLanguage.RUST, False),
        (CodeLanguage.KOTLIN, False),
    ],
)
def test_supports_language_parametrized(
    language: CodeLanguage, expected: bool
) -> None:
    """Test language support for various languages."""
    provider = JavaParserProvider()
    assert provider.supports_language(language) == expected
