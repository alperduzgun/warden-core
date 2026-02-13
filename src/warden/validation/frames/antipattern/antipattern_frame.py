"""
Anti-Pattern Detection Frame (Universal AST)

Detects common code anti-patterns across ALL Tree-sitter supported languages (50+).

Architecture:
1. ASTProviderRegistry → Best provider for language
2. Universal AST queries → Language-agnostic pattern detection
3. Regex fallback → When AST unavailable

Detections:
- Exception swallowing (bare/empty catch blocks)
- God classes (classes > 500 lines)
- Debug output in production
- TODO/FIXME comments (technical debt markers)
- Generic exception raising/throwing

Priority: HIGH
Blocker: TRUE (for critical anti-patterns)
Scope: FILE_LEVEL

Author: Warden Team
Version: 3.0.0 (Universal AST)
"""

import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from warden.ast.application.provider_registry import ASTProviderRegistry
from warden.ast.domain.enums import CodeLanguage

# AST imports
from warden.ast.domain.models import ASTNode
from warden.shared.infrastructure.logging import get_logger
from warden.validation.domain.enums import (
    FrameApplicability,
    FrameCategory,
    FramePriority,
    FrameScope,
)
from warden.validation.domain.frame import (
    CodeFile,
    Finding,
    FrameResult,
    Remediation,
    ValidationFrame,
)

# Detectors
from warden.validation.frames.antipattern.detectors import (
    ClassSizeDetector,
    DebugDetector,
    ExceptionDetector,
    TodoDetector,
)

# Types
from warden.validation.frames.antipattern.types import (
    AntiPatternSeverity,
    AntiPatternViolation,
)

logger = get_logger(__name__)


class AntiPatternFrame(ValidationFrame):
    """
    Universal Anti-Pattern Detection Frame (50+ Languages)

    Uses Universal AST via Tree-sitter for language-agnostic detection.
    Falls back to regex patterns when AST unavailable.

    Supported via Tree-sitter:
    - Python, JavaScript, TypeScript, Java, C#, Go, Rust, Ruby, PHP,
    - Kotlin, Swift, Scala, Dart, C, C++, and 35+ more languages

    Detections:
    - Empty/bare catch blocks (exception swallowing)
    - God classes (500+ lines)
    - Debug output in production
    - TODO/FIXME comments
    - Generic exception throwing
    - Language-specific anti-patterns
    """

    # Frame metadata
    name = "Anti-Pattern Detection"
    description = "Detects anti-patterns across 50+ languages using Universal AST"
    category = FrameCategory.GLOBAL
    priority = FramePriority.HIGH
    scope = FrameScope.FILE_LEVEL
    is_blocker = True
    version = "3.0.0"
    author = "Warden Team"
    applicability = [FrameApplicability.ALL]

    # Singleton registry instance (lazy loaded)
    _registry: ASTProviderRegistry | None = None

    @property
    def frame_id(self) -> str:
        return "antipattern"

    def __init__(self, config: dict[str, Any] | None = None):
        """Initialize AntiPatternFrame with detectors."""
        super().__init__(config)

        config_dict = self.config if isinstance(self.config, dict) else {}

        # Thresholds (universal)
        self.max_class_lines = config_dict.get("max_class_lines", 500)
        self.max_function_lines = config_dict.get("max_function_lines", 100)
        self.max_file_lines = config_dict.get("max_file_lines", 1000)

        # Check toggles
        self.check_exception_handling = config_dict.get("check_exception_handling", True)
        self.check_god_class = config_dict.get("check_god_class", True)
        self.check_debug_output = config_dict.get("check_debug_output", True)
        self.check_todo_fixme = config_dict.get("check_todo_fixme", True)
        self.check_generic_exception = config_dict.get("check_generic_exception", True)

        # Filtering
        self.ignore_test_files = config_dict.get("ignore_test_files", True)

        # Use AST when available
        self.prefer_ast = config_dict.get("prefer_ast", True)

        # Initialize detectors
        self._exception_detector = ExceptionDetector()
        self._class_size_detector = ClassSizeDetector(
            max_class_lines=self.max_class_lines,
            max_file_lines=self.max_file_lines,
        )
        self._debug_detector = DebugDetector()
        self._todo_detector = TodoDetector()

    @classmethod
    def _get_registry(cls) -> ASTProviderRegistry:
        """Get or create AST provider registry (lazy singleton)."""
        if cls._registry is None:
            cls._registry = ASTProviderRegistry()
            # Register tree-sitter provider
            try:
                from warden.ast.providers.tree_sitter_provider import TreeSitterProvider

                cls._registry.register(TreeSitterProvider())
            except ImportError:
                logger.debug("tree_sitter_provider_not_available")
            # Register Python native provider if available
            try:
                from warden.ast.providers.python_provider import PythonASTProvider

                cls._registry.register(PythonASTProvider())
            except ImportError:
                pass
        return cls._registry

    async def execute_async(self, code_file: CodeFile) -> FrameResult:
        """Execute anti-pattern detection on a code file."""
        start_time = time.perf_counter()

        # Detect language from CodeFile or extension
        language = self._detect_language(code_file)

        if not language:
            return self._create_skipped_result(start_time, "Unsupported file type")

        logger.info(
            "antipattern_frame_started",
            file_path=code_file.path,
            language=language.value if isinstance(language, CodeLanguage) else language,
        )

        # Skip test files if configured
        if self.ignore_test_files and self._is_test_file(code_file.path):
            return self._create_skipped_result(start_time, "Test file (ignored)")

        violations: list[AntiPatternViolation] = []
        checks_executed: list[str] = []
        lines = code_file.content.split("\n")

        # Try to get Universal AST
        ast_root: ASTNode | None = None
        if self.prefer_ast and isinstance(language, CodeLanguage):
            ast_root = await self._get_ast(code_file.content, language, code_file.path, code_file=code_file)

        # Run detections using modular detectors
        if self.check_exception_handling or self.check_generic_exception:
            checks_executed.append("exception_handling")
            violations.extend(self._exception_detector.detect(code_file, language, lines, ast_root))

        if self.check_god_class:
            checks_executed.append("god_class")
            violations.extend(self._class_size_detector.detect(code_file, language, lines, ast_root))

        if self.check_debug_output:
            checks_executed.append("debug_output")
            violations.extend(self._debug_detector.detect(code_file, language, lines, ast_root))

        if self.check_todo_fixme:
            checks_executed.append("todo_fixme")
            violations.extend(self._todo_detector.detect(code_file, language, lines, ast_root))

        # Convert to findings
        findings = self._violations_to_findings(violations)

        # Determine status
        has_critical = any(v.severity == AntiPatternSeverity.CRITICAL for v in violations)
        has_high = any(v.severity == AntiPatternSeverity.HIGH for v in violations)

        if has_critical:
            status = "failed"
            result_is_blocker = True
        elif has_high:
            status = "failed"
            result_is_blocker = False
        elif violations:
            status = "warning"
            result_is_blocker = False
        else:
            status = "passed"
            result_is_blocker = False

        duration = time.perf_counter() - start_time

        lang_str = language.value if isinstance(language, CodeLanguage) else str(language)
        logger.info(
            "antipattern_frame_completed",
            file_path=code_file.path,
            language=lang_str,
            status=status,
            violations=len(violations),
            duration=f"{duration:.2f}s",
            used_ast=ast_root is not None,
        )

        return FrameResult(
            frame_id=self.frame_id,
            frame_name=self.name,
            status=status,
            duration=duration,
            issues_found=len(violations),
            is_blocker=result_is_blocker,
            findings=findings,
            metadata={
                "language": lang_str,
                "total_violations": len(violations),
                "critical": sum(1 for v in violations if v.severity == AntiPatternSeverity.CRITICAL),
                "high": sum(1 for v in violations if v.severity == AntiPatternSeverity.HIGH),
                "checks_executed": checks_executed,
                "used_ast": ast_root is not None,
            },
        )

    # =========================================================================
    # LANGUAGE DETECTION
    # =========================================================================

    def _detect_language(self, code_file: CodeFile) -> CodeLanguage | None:
        """Detect language from file, returning CodeLanguage enum."""
        # Try LanguageRegistry first
        try:
            from warden.shared.languages.registry import LanguageRegistry

            lang = LanguageRegistry.get_language_from_path(code_file.path)
            if lang and lang != CodeLanguage.UNKNOWN:
                return lang
        except ImportError:
            pass

        # Fallback: map extension manually
        ext_map = {
            ".py": CodeLanguage.PYTHON,
            ".js": CodeLanguage.JAVASCRIPT,
            ".mjs": CodeLanguage.JAVASCRIPT,
            ".ts": CodeLanguage.TYPESCRIPT,
            ".tsx": CodeLanguage.TSX,
            ".jsx": CodeLanguage.JAVASCRIPT,
            ".java": CodeLanguage.JAVA,
            ".cs": CodeLanguage.CSHARP,
            ".go": CodeLanguage.GO,
            ".rs": CodeLanguage.RUST,
            ".rb": CodeLanguage.RUBY,
            ".php": CodeLanguage.PHP,
            ".kt": CodeLanguage.KOTLIN,
            ".swift": CodeLanguage.SWIFT,
            ".scala": CodeLanguage.SCALA,
            ".dart": CodeLanguage.DART,
            ".cpp": CodeLanguage.CPP,
            ".cc": CodeLanguage.CPP,
            ".c": CodeLanguage.C,
            ".h": CodeLanguage.C,
            ".hpp": CodeLanguage.CPP,
        }
        ext = Path(code_file.path).suffix.lower()
        return ext_map.get(ext)

    def _is_test_file(self, file_path: str) -> bool:
        """Check if file is a test file (language-agnostic)."""
        path = Path(file_path)
        path_str = str(path).lower()

        # Common test directories
        if any(d in path_str for d in ["/test/", "/tests/", "/__tests__/", "/spec/", "/specs/"]):
            return True

        name = path.stem.lower()
        test_patterns = ["test_", "_test", ".test", ".spec", "_spec"]
        return any(p in name for p in test_patterns)

    # =========================================================================
    # AST ACQUISITION
    # =========================================================================

    async def _get_ast(
        self,
        content: str,
        language: CodeLanguage,
        file_path: str,
        code_file: Any = None,
    ) -> ASTNode | None:
        """Get Universal AST for content using best available provider."""
        # Cache-first: use pre-parsed result if available
        cached = code_file.metadata.get("_cached_parse_result") if code_file and code_file.metadata else None
        if cached and (cached.is_success() or cached.is_partial()) and cached.ast_root:
            return cached.ast_root

        # Fallback: on-demand parse
        registry = self._get_registry()
        provider = registry.get_provider(language)

        if not provider:
            logger.debug("no_ast_provider", language=language.value)
            return None

        try:
            result = await provider.parse(content, language, file_path)
            if result.is_success() or result.is_partial():
                return result.ast_root
        except Exception as e:
            logger.debug("ast_parse_failed", language=language.value, error=str(e))

        return None

    # =========================================================================
    # RESULT CONVERSION
    # =========================================================================

    def _violations_to_findings(self, violations: list[AntiPatternViolation]) -> list[Finding]:
        """Convert violations to Frame findings."""
        findings = []

        severity_map = {
            AntiPatternSeverity.CRITICAL: "critical",
            AntiPatternSeverity.HIGH: "high",
            AntiPatternSeverity.MEDIUM: "medium",
            AntiPatternSeverity.LOW: "low",
        }

        for v in violations:
            location = f"{Path(v.file_path).name}:{v.line}"

            remediation = None
            if v.suggestion:
                remediation = Remediation(description=v.suggestion, code="")

            finding = Finding(
                id=v.pattern_id,
                severity=severity_map.get(v.severity, "medium"),
                message=v.message,
                location=location,
                line=v.line,
                column=v.column,
                detail=f"**Pattern:** {v.pattern_name}\n\n**Code:**\n```\n{v.code_snippet}\n```\n\n**Suggestion:** {v.suggestion}",
                code=v.code_snippet,
                is_blocker=v.is_blocker,
                remediation=remediation,
            )
            findings.append(finding)

        return findings

    def _create_skipped_result(self, start_time: float, reason: str) -> FrameResult:
        """Create a skipped result."""
        duration = time.perf_counter() - start_time
        return FrameResult(
            frame_id=self.frame_id,
            frame_name=self.name,
            status="passed",
            duration=duration,
            issues_found=0,
            is_blocker=False,
            findings=[],
            metadata={"skipped": True, "reason": reason},
        )
