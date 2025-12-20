"""
Tree-sitter Universal AST Provider.

Uses tree-sitter for parsing 40+ programming languages.
Priority: TREE_SITTER (fallback for languages without native provider).
"""

import time
from typing import Optional, List

from warden.ast.application.provider_interface import IASTProvider
from warden.ast.domain.models import (
    ASTNode,
    ASTProviderMetadata,
    ParseError,
    ParseResult,
    SourceLocation,
)
from warden.ast.domain.enums import (
    ASTNodeType,
    ASTProviderPriority,
    CodeLanguage,
    ParseStatus,
)

# Try to import tree-sitter (optional dependency)
try:
    import tree_sitter

    TREE_SITTER_AVAILABLE = True
except ImportError:
    TREE_SITTER_AVAILABLE = False


class TreeSitterProvider(IASTProvider):
    """
    Universal AST provider using tree-sitter.

    Supports 40+ programming languages through tree-sitter grammars.
    Requires tree-sitter package to be installed.

    Advantages:
        - Multi-language support (40+ languages)
        - Error recovery (partial AST on syntax errors)
        - Incremental parsing
        - Fast performance

    Limitations:
        - Requires tree-sitter installation
        - Language grammars must be installed separately
        - Less detailed than native parsers

    Installation:
        pip install tree-sitter
        # Then install language grammars as needed
    """

    def __init__(self) -> None:
        """Initialize Tree-sitter provider."""
        self._metadata = ASTProviderMetadata(
            name="tree-sitter",
            priority=ASTProviderPriority.TREE_SITTER,
            supported_languages=[
                CodeLanguage.PYTHON,
                CodeLanguage.JAVASCRIPT,
                CodeLanguage.TYPESCRIPT,
                CodeLanguage.JAVA,
                CodeLanguage.C,
                CodeLanguage.CPP,
                CodeLanguage.GO,
                CodeLanguage.RUST,
                # Add more as grammars are available
            ],
            version="1.0.0",
            description="Universal AST parser using tree-sitter (40+ languages)",
            author="Warden Core Team",
            requires_installation=True,
            installation_command="pip install tree-sitter",
        )

        self._parsers = {}  # Language -> Parser cache
        self._available = TREE_SITTER_AVAILABLE

    @property
    def metadata(self) -> ASTProviderMetadata:
        """Get provider metadata."""
        return self._metadata

    async def parse(
        self,
        source_code: str,
        language: CodeLanguage,
        file_path: Optional[str] = None,
    ) -> ParseResult:
        """
        Parse source code using tree-sitter.

        Args:
            source_code: Source code to parse
            language: Programming language
            file_path: Optional file path for error reporting

        Returns:
            ParseResult with AST and any errors
        """
        if not self._available:
            return ParseResult(
                status=ParseStatus.FAILED,
                language=language,
                provider_name=self.metadata.name,
                errors=[
                    ParseError(
                        message="tree-sitter not installed. Run: pip install tree-sitter",
                        severity="error",
                    )
                ],
            )

        if not self.supports_language(language):
            return ParseResult(
                status=ParseStatus.UNSUPPORTED,
                language=language,
                provider_name=self.metadata.name,
                errors=[
                    ParseError(
                        message=f"Language {language.value} not supported by tree-sitter provider",
                        severity="error",
                    )
                ],
            )

        start_time = time.time()

        try:
            # TODO: Implement actual tree-sitter parsing
            # This is a placeholder implementation
            # Real implementation would:
            # 1. Get/create parser for language
            # 2. Parse source code
            # 3. Convert tree-sitter tree to universal AST
            # 4. Handle errors and warnings

            parse_time_ms = (time.time() - start_time) * 1000

            return ParseResult(
                status=ParseStatus.FAILED,
                language=language,
                provider_name=self.metadata.name,
                errors=[
                    ParseError(
                        message="Tree-sitter provider not fully implemented yet",
                        severity="error",
                    )
                ],
                parse_time_ms=parse_time_ms,
                file_path=file_path,
            )

        except Exception as e:
            parse_time_ms = (time.time() - start_time) * 1000

            return ParseResult(
                status=ParseStatus.FAILED,
                language=language,
                provider_name=self.metadata.name,
                errors=[
                    ParseError(
                        message=f"Parse error: {str(e)}",
                        severity="error",
                    )
                ],
                parse_time_ms=parse_time_ms,
                file_path=file_path,
            )

    def supports_language(self, language: CodeLanguage) -> bool:
        """Check if provider supports a language."""
        return language in self.metadata.supported_languages

    async def validate(self) -> bool:
        """
        Validate that tree-sitter is installed.

        Returns:
            True if tree-sitter is available
        """
        return self._available

    async def cleanup(self) -> None:
        """Cleanup parser cache."""
        self._parsers.clear()
