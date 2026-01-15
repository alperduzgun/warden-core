"""
Base contract extractor using tree-sitter.

All platform-specific extractors inherit from BaseContractExtractor.

Resilience Features:
- Timeout: Prevents indefinite hangs on file parsing
- Retry: Handles transient failures with exponential backoff
- Circuit Breaker: Prevents cascading failures when parser is down
- Bulkhead: Limits concurrent file operations
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Type, Any

from warden.validation.frames.spec.models import (
    Contract,
    PlatformType,
    PlatformRole,
)
from warden.ast.providers.tree_sitter_provider import TreeSitterProvider
from warden.ast.domain.enums import CodeLanguage
from warden.shared.infrastructure.logging import get_logger
from warden.shared.infrastructure.resilience import (
    with_timeout,
    with_retry,
    CircuitBreaker,
    CircuitBreakerConfig,
    Bulkhead,
    BulkheadConfig,
    RetryConfig,
    TimeoutError as ResilienceTimeoutError,
    CircuitBreakerOpen,
)

logger = get_logger(__name__)


@dataclass
class ExtractorResilienceConfig:
    """Resilience configuration for extractors."""

    # Timeout for file parsing (seconds)
    parse_timeout: float = 30.0

    # Timeout for entire extraction (seconds)
    extraction_timeout: float = 300.0  # 5 minutes

    # Retry configuration
    retry_max_attempts: int = 3
    retry_initial_delay: float = 1.0
    retry_max_delay: float = 10.0

    # Circuit breaker configuration
    circuit_failure_threshold: int = 5
    circuit_timeout_duration: float = 60.0

    # Bulkhead configuration (concurrent file operations)
    max_concurrent_files: int = 10


class BaseContractExtractor(ABC):
    """
    Base class for platform-specific contract extractors.

    Uses tree-sitter for AST parsing and extracts:
    - Operations (API calls/endpoints)
    - Models (DTOs, entities)
    - Enums

    Resilience Features (Chaos Engineering Ready):
    - Timeout: Prevents indefinite hangs on slow file systems
    - Retry: Handles transient I/O errors with exponential backoff
    - Circuit Breaker: Fast-fails when tree-sitter parser is failing
    - Bulkhead: Limits concurrent file parsing to prevent resource exhaustion
    """

    # To be defined by subclasses
    platform_type: PlatformType
    supported_languages: List[CodeLanguage] = []
    file_patterns: List[str] = []  # Glob patterns for files to scan

    def __init__(
        self,
        project_root: Path,
        role: PlatformRole,
        resilience_config: Optional[ExtractorResilienceConfig] = None,
    ):
        """
        Initialize extractor with resilience support.

        Args:
            project_root: Root directory of the platform project
            role: Consumer or provider role
            resilience_config: Configuration for fault tolerance
        """
        self.project_root = project_root
        self.role = role
        self.tree_sitter = TreeSitterProvider()
        self.resilience_config = resilience_config or ExtractorResilienceConfig()

        # Initialize resilience components
        self._circuit_breaker = CircuitBreaker(
            f"extractor_{self.platform_type.value if hasattr(self, 'platform_type') else 'unknown'}",
            CircuitBreakerConfig(
                failure_threshold=self.resilience_config.circuit_failure_threshold,
                timeout_duration=self.resilience_config.circuit_timeout_duration,
            ),
        )

        self._bulkhead = Bulkhead(
            f"file_ops_{self.platform_type.value if hasattr(self, 'platform_type') else 'unknown'}",
            BulkheadConfig(
                max_concurrent=self.resilience_config.max_concurrent_files,
            ),
        )

        # Track extraction statistics for observability
        self._stats = {
            "files_processed": 0,
            "files_failed": 0,
            "timeouts": 0,
            "retries": 0,
            "circuit_breaks": 0,
        }

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
        Parse a file using tree-sitter with resilience patterns.

        Applies:
        - Circuit Breaker: Fast-fails if parser is consistently failing
        - Bulkhead: Limits concurrent file operations
        - Timeout: Prevents indefinite hangs
        - Retry: Handles transient I/O errors

        Args:
            file_path: Path to the file
            language: Programming language

        Returns:
            ParseResult with AST root, or None on error
        """
        # Check circuit breaker first (fast-fail)
        try:
            state = self._circuit_breaker.state
            if state.value == "open":
                self._stats["circuit_breaks"] += 1
                logger.warning(
                    "parse_circuit_open",
                    file=str(file_path),
                    message="Circuit breaker is open, skipping file",
                )
                return None
        except Exception:
            pass  # If circuit breaker check fails, continue anyway

        async def do_parse() -> Optional[Any]:
            """Inner function for retry logic."""
            # Use bulkhead to limit concurrent operations
            async with self._bulkhead:
                # Apply timeout to the actual parsing
                async def parse_with_timeout():
                    content = file_path.read_text(encoding="utf-8")
                    return await self.tree_sitter.parse(content, language, str(file_path))

                result = await with_timeout(
                    parse_with_timeout(),
                    self.resilience_config.parse_timeout,
                    f"parse_{file_path.name}",
                )

                if result.status.value == "success":
                    self._stats["files_processed"] += 1
                    return result
                else:
                    logger.warning(
                        "parse_failed",
                        file=str(file_path),
                        status=result.status.value,
                        errors=[e.message for e in result.errors],
                    )
                    return None

        try:
            # Wrap with circuit breaker
            async with self._circuit_breaker:
                # Apply retry with exponential backoff
                retry_config = RetryConfig(
                    max_attempts=self.resilience_config.retry_max_attempts,
                    initial_delay=self.resilience_config.retry_initial_delay,
                    max_delay=self.resilience_config.retry_max_delay,
                    retryable_exceptions=(IOError, OSError, ResilienceTimeoutError),
                )

                return await with_retry(
                    do_parse,
                    retry_config,
                    f"parse_{file_path.name}",
                )

        except ResilienceTimeoutError:
            self._stats["timeouts"] += 1
            logger.warning(
                "parse_timeout",
                file=str(file_path),
                timeout=self.resilience_config.parse_timeout,
            )
            return None

        except CircuitBreakerOpen as e:
            self._stats["circuit_breaks"] += 1
            logger.warning(
                "parse_circuit_open",
                file=str(file_path),
                retry_after=e.retry_after,
            )
            return None

        except Exception as e:
            self._stats["files_failed"] += 1
            logger.error(
                "parse_error",
                file=str(file_path),
                error=str(e),
                error_type=type(e).__name__,
            )
            return None

    def get_extraction_stats(self) -> Dict[str, Any]:
        """
        Get extraction statistics for observability.

        Returns:
            Dictionary with extraction stats
        """
        return {
            **self._stats,
            "circuit_breaker_state": self._circuit_breaker.state.value,
            "bulkhead_available": self._bulkhead.available,
        }

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
    resilience_config: Optional[ExtractorResilienceConfig] = None,
) -> Optional[BaseContractExtractor]:
    """
    Get an extractor instance for a platform.

    Args:
        platform_type: Platform type
        project_root: Project root directory
        role: Consumer or provider role
        resilience_config: Optional resilience configuration

    Returns:
        Extractor instance or None if not supported
    """
    extractor_class = ExtractorRegistry.get(platform_type)
    if extractor_class:
        return extractor_class(project_root, role, resilience_config)
    return None
