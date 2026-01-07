"""
Base contract extractor using tree-sitter.

All platform-specific extractors inherit from BaseContractExtractor.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Optional, Type, Any

from warden.validation.frames.spec.models import (
    Contract,
    OperationDefinition,
    ModelDefinition,
    EnumDefinition,
    PlatformType,
    PlatformRole,
)
from warden.ast.providers.tree_sitter_provider import TreeSitterProvider
from warden.ast.domain.enums import CodeLanguage
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)


class BaseContractExtractor(ABC):
    """
    Base class for platform-specific contract extractors.

    Uses tree-sitter for AST parsing and extracts:
    - Operations (API calls/endpoints)
    - Models (DTOs, entities)
    - Enums
    """

    # To be defined by subclasses
    platform_type: PlatformType
    supported_languages: List[CodeLanguage] = []
    file_patterns: List[str] = []  # Glob patterns for files to scan

    def __init__(self, project_root: Path, role: PlatformRole):
        """
        Initialize extractor.

        Args:
            project_root: Root directory of the platform project
            role: Consumer or provider role
        """
        self.project_root = project_root
        self.role = role
        self.tree_sitter = TreeSitterProvider()

    @abstractmethod
    async def extract(self) -> Contract:
        """
        Extract contract from the platform.

        Returns:
            Contract with operations, models, and enums
        """
        pass

    async def _parse_file(self, file_path: Path, language: CodeLanguage) -> Optional[Any]:
        """
        Parse a file using tree-sitter.

        Args:
            file_path: Path to the file
            language: Programming language

        Returns:
            ParseResult with AST root, or None on error
        """
        try:
            content = file_path.read_text(encoding="utf-8")
            result = await self.tree_sitter.parse(content, language, str(file_path))

            if result.status.value == "success":
                return result
            else:
                logger.warning(
                    "parse_failed",
                    file=str(file_path),
                    status=result.status.value,
                    errors=[e.message for e in result.errors],
                )
                return None

        except Exception as e:
            logger.error(
                "parse_error",
                file=str(file_path),
                error=str(e),
            )
            return None

    def _find_files(self) -> List[Path]:
        """
        Find files to scan based on file_patterns.

        Returns:
            List of file paths matching the patterns
        """
        files = []
        for pattern in self.file_patterns:
            files.extend(self.project_root.glob(pattern))

        # Filter out test files, generated files, etc.
        filtered = [
            f for f in files
            if not any(exclude in str(f) for exclude in [
                "test", "spec", "mock", "generated", "node_modules",
                ".dart_tool", "build", "dist", ".gradle"
            ])
        ]

        logger.info(
            "files_found",
            platform=self.platform_type.value,
            total=len(files),
            filtered=len(filtered),
        )

        return filtered


class ExtractorRegistry:
    """
    Registry for platform-specific extractors.
    """

    _extractors: Dict[PlatformType, Type[BaseContractExtractor]] = {}

    @classmethod
    def register(cls, extractor_class: Type[BaseContractExtractor]) -> Type[BaseContractExtractor]:
        """
        Register an extractor class.

        Can be used as a decorator:
            @ExtractorRegistry.register
            class FlutterExtractor(BaseContractExtractor):
                ...
        """
        cls._extractors[extractor_class.platform_type] = extractor_class
        logger.debug(
            "extractor_registered",
            platform=extractor_class.platform_type.value,
            extractor=extractor_class.__name__,
        )
        return extractor_class

    @classmethod
    def get(cls, platform_type: PlatformType) -> Optional[Type[BaseContractExtractor]]:
        """
        Get extractor class for a platform type.

        Args:
            platform_type: Platform type

        Returns:
            Extractor class or None if not registered
        """
        return cls._extractors.get(platform_type)

    @classmethod
    def get_all(cls) -> Dict[PlatformType, Type[BaseContractExtractor]]:
        """Get all registered extractors."""
        return cls._extractors.copy()


def get_extractor(
    platform_type: PlatformType,
    project_root: Path,
    role: PlatformRole,
) -> Optional[BaseContractExtractor]:
    """
    Get an extractor instance for a platform.

    Args:
        platform_type: Platform type
        project_root: Project root directory
        role: Consumer or provider role

    Returns:
        Extractor instance or None if not supported
    """
    extractor_class = ExtractorRegistry.get(platform_type)
    if extractor_class:
        return extractor_class(project_root, role)
    return None
