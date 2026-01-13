"""
AST Provider Interface.

Defines the contract that all AST providers must implement.
This enables pluggable, language-specific parsers.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from warden.ast.domain.models import (
    ASTProviderMetadata,
    ParseResult,
)
from warden.ast.domain.enums import CodeLanguage


class IASTProvider(ABC):
    """
    Interface for AST providers.

    All AST providers (tree-sitter, native parsers, community plugins) must
    implement this interface. This ensures consistent behavior across providers.

    Example providers:
        - TreeSitterProvider: Universal parser for 40+ languages
        - PythonASTProvider: Native Python ast module (higher priority)
        - TypeScriptASTProvider: Community plugin using TypeScript compiler API
        - KotlinASTProvider: Community plugin for Kotlin parsing
    """

    @property
    @abstractmethod
    def metadata(self) -> ASTProviderMetadata:
        """
        Get provider metadata.

        Returns:
            Metadata including name, priority, supported languages
        """
        pass

    @abstractmethod
    async def parse(
        self,
        source_code: str,
        language: CodeLanguage,
        file_path: Optional[str] = None,
    ) -> ParseResult:
        """
        Parse source code into universal AST.

        Args:
            source_code: Source code to parse
            language: Programming language of the code
            file_path: Optional path to source file (for error reporting)

        Returns:
            ParseResult containing AST and any errors

        Raises:
            NotImplementedError: If language is not supported
            ValueError: If source_code is invalid
        """
        pass

    @abstractmethod
    def extract_dependencies(self, source_code: str, language: CodeLanguage) -> List[str]:
        """
        Extract raw dependency strings (imports, requires, includes).
        
        Args:
            source_code: Source code to analyze
            language: Programming language of the code
            
        Returns:
            List of raw import/dependency strings
        """
        pass

    @abstractmethod
    def supports_language(self, language: CodeLanguage) -> bool:
        """
        Check if provider supports a language.

        Args:
            language: Language to check

        Returns:
            True if language is supported
        """
        pass

    @abstractmethod
    async def validate(self) -> bool:
        """
        Validate that provider is ready to use.

        Checks if all dependencies are installed and provider is functional.

        Returns:
            True if provider is ready, False otherwise
        """
        pass

    def get_priority(self, language: CodeLanguage) -> int:
        """
        Get provider priority for a specific language.

        Default implementation returns the provider's base priority.
        Override to provide language-specific priorities.

        Args:
            language: Language to get priority for

        Returns:
            Priority value (lower is higher priority)
        """
        return self.metadata.priority.value

    async def cleanup(self) -> None:
        """
        Cleanup provider resources.

        Called when provider is no longer needed.
        Override if provider needs cleanup (e.g., close connections).
        """
        pass
