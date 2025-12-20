"""
Orphan Frame - Dead code and unused code detection.

Built-in checks:
- Unused imports detection
- Unreferenced functions detection
- Unreferenced classes detection
- Dead code (unreachable statements) detection

Priority: MEDIUM (warning)
"""

import time
from typing import List, Dict, Any

from warden.validation.domain.frame import (
    ValidationFrame,
    FrameResult,
    Finding,
    CodeFile,
)
from warden.validation.domain.enums import (
    FrameCategory,
    FramePriority,
    FrameScope,
    FrameApplicability,
)
from warden.validation.frames.orphan_detector import OrphanDetector, OrphanFinding
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)


class OrphanFrame(ValidationFrame):
    """
    Orphan code validation frame - Detects dead and unused code.

    This frame detects:
    - Unused imports (imported but never referenced)
    - Unreferenced functions (defined but never called)
    - Unreferenced classes (defined but never used)
    - Dead code (unreachable statements after return/break/continue)

    Priority: MEDIUM (informational warning)
    Applicability: Python only (AST-based analysis)
    """

    # Required metadata
    name = "Orphan Code Analysis"
    description = "Detects unused imports, unreferenced functions/classes, and dead code"
    category = FrameCategory.LANGUAGE_SPECIFIC
    priority = FramePriority.MEDIUM
    scope = FrameScope.FILE_LEVEL
    is_blocker = False  # Dead code is warning, not blocker
    version = "1.0.0"
    author = "Warden Team"
    applicability = [FrameApplicability.PYTHON]  # Python-specific (AST-based)

    def __init__(self, config: Dict[str, Any] | None = None) -> None:
        """
        Initialize OrphanFrame.

        Args:
            config: Frame configuration
                - ignore_private: bool (default: True) - Ignore private functions/classes
                - ignore_test_files: bool (default: True) - Ignore test files
                - ignore_imports: List[str] - Import names to ignore
        """
        super().__init__(config)

        # Configuration options
        self.ignore_private = self.config.get("ignore_private", True)
        self.ignore_test_files = self.config.get("ignore_test_files", True)
        self.ignore_imports = set(self.config.get("ignore_imports", []))

    async def execute(self, code_file: CodeFile) -> FrameResult:
        """
        Execute orphan code detection on code file.

        Args:
            code_file: Code file to validate

        Returns:
            FrameResult with orphan code findings
        """
        start_time = time.perf_counter()

        logger.info(
            "orphan_frame_started",
            file_path=code_file.path,
            language=code_file.language,
        )

        # Check if file is applicable
        if not self._is_applicable(code_file):
            logger.info(
                "orphan_frame_skipped",
                file_path=code_file.path,
                reason="Not a Python file",
            )
            return self._create_skipped_result(start_time)

        # Run orphan detection
        try:
            detector = OrphanDetector(code_file.content, code_file.path)
            orphan_findings = detector.detect_all()

            # Filter findings based on config
            filtered_findings = self._filter_findings(orphan_findings, code_file)

            # Convert to Frame findings
            findings = self._convert_to_findings(filtered_findings, code_file)

            # Determine status
            status = self._determine_status(findings)

            duration = time.perf_counter() - start_time

            logger.info(
                "orphan_frame_completed",
                file_path=code_file.path,
                status=status,
                total_findings=len(findings),
                duration=f"{duration:.2f}s",
            )

            return FrameResult(
                frame_id=self.frame_id,
                frame_name=self.name,
                status=status,
                duration=duration,
                issues_found=len(findings),
                is_blocker=False,  # Orphan code is never a blocker
                findings=findings,
                metadata={
                    "total_orphans": len(orphan_findings),
                    "filtered_orphans": len(filtered_findings),
                    "unused_imports": sum(
                        1 for f in filtered_findings if f.orphan_type == "unused_import"
                    ),
                    "unreferenced_functions": sum(
                        1
                        for f in filtered_findings
                        if f.orphan_type == "unreferenced_function"
                    ),
                    "unreferenced_classes": sum(
                        1
                        for f in filtered_findings
                        if f.orphan_type == "unreferenced_class"
                    ),
                    "dead_code": sum(
                        1 for f in filtered_findings if f.orphan_type == "dead_code"
                    ),
                },
            )

        except Exception as e:
            logger.error(
                "orphan_frame_error",
                file_path=code_file.path,
                error=str(e),
            )

            duration = time.perf_counter() - start_time
            return FrameResult(
                frame_id=self.frame_id,
                frame_name=self.name,
                status="failed",
                duration=duration,
                issues_found=0,
                is_blocker=False,
                findings=[],
                metadata={
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
            )

    def _is_applicable(self, code_file: CodeFile) -> bool:
        """
        Check if frame is applicable to code file.

        Args:
            code_file: Code file to check

        Returns:
            True if frame should run
        """
        # Check language
        if code_file.language.lower() != "python":
            return False

        # Check if test file should be ignored
        if self.ignore_test_files:
            if "test_" in code_file.path or "_test.py" in code_file.path:
                return False

        return True

    def _filter_findings(
        self, findings: List[OrphanFinding], code_file: CodeFile
    ) -> List[OrphanFinding]:
        """
        Filter findings based on configuration.

        Args:
            findings: Raw orphan findings
            code_file: Code file context

        Returns:
            Filtered findings
        """
        filtered: List[OrphanFinding] = []

        for finding in findings:
            # Filter ignored imports
            if finding.orphan_type == "unused_import":
                if finding.name in self.ignore_imports:
                    continue

            # Filter private functions/classes if configured
            if self.ignore_private:
                if finding.orphan_type in [
                    "unreferenced_function",
                    "unreferenced_class",
                ]:
                    if finding.name.startswith("_"):
                        continue

            filtered.append(finding)

        return filtered

    def _convert_to_findings(
        self, orphan_findings: List[OrphanFinding], code_file: CodeFile
    ) -> List[Finding]:
        """
        Convert OrphanFinding objects to Frame Finding objects.

        Args:
            orphan_findings: List of orphan findings
            code_file: Code file context

        Returns:
            List of Frame Finding objects
        """
        findings: List[Finding] = []

        for i, orphan in enumerate(orphan_findings):
            # Determine severity based on orphan type
            severity = self._get_severity(orphan.orphan_type)

            # Create suggestion
            suggestion = self._get_suggestion(orphan.orphan_type)

            finding = Finding(
                id=f"{self.frame_id}-{orphan.orphan_type}-{i}",
                severity=severity,
                message=orphan.reason,
                location=f"{code_file.path}:{orphan.line_number}",
                detail=suggestion,
                code=orphan.code_snippet,
            )
            findings.append(finding)

        return findings

    def _get_severity(self, orphan_type: str) -> str:
        """
        Get severity for orphan type.

        Args:
            orphan_type: Type of orphan code

        Returns:
            Severity level ('low' | 'medium')
        """
        severity_map = {
            "unused_import": "low",  # Cleanup only
            "unreferenced_function": "medium",  # Potential maintenance issue
            "unreferenced_class": "medium",  # Potential maintenance issue
            "dead_code": "medium",  # Likely a bug
        }

        return severity_map.get(orphan_type, "low")

    def _get_suggestion(self, orphan_type: str) -> str:
        """
        Get suggestion for fixing orphan code.

        Args:
            orphan_type: Type of orphan code

        Returns:
            Suggestion text
        """
        suggestions = {
            "unused_import": (
                "Remove this unused import to keep the code clean.\n"
                "Unused imports increase file size and may cause confusion."
            ),
            "unreferenced_function": (
                "This function is never called in the codebase.\n"
                "Consider:\n"
                "1. Remove it if it's truly unused\n"
                "2. Export it if it's meant to be a public API\n"
                "3. Add tests if it's meant to be used"
            ),
            "unreferenced_class": (
                "This class is never instantiated in the codebase.\n"
                "Consider:\n"
                "1. Remove it if it's truly unused\n"
                "2. Export it if it's meant to be a public API\n"
                "3. Add tests if it's meant to be used"
            ),
            "dead_code": (
                "This code is unreachable and will never execute.\n"
                "Remove it or restructure the logic to make it reachable."
            ),
        }

        return suggestions.get(orphan_type, "Consider removing or refactoring this code.")

    def _determine_status(self, findings: List[Finding]) -> str:
        """
        Determine frame status based on findings.

        Args:
            findings: All findings from analysis

        Returns:
            Status: 'passed' | 'warning'
        """
        if not findings:
            return "passed"

        # Orphan code is always a warning, never a failure
        return "warning"

    def _create_skipped_result(self, start_time: float) -> FrameResult:
        """
        Create result for skipped execution.

        Args:
            start_time: Start time for duration calculation

        Returns:
            FrameResult indicating skip
        """
        duration = time.perf_counter() - start_time

        return FrameResult(
            frame_id=self.frame_id,
            frame_name=self.name,
            status="passed",
            duration=duration,
            issues_found=0,
            is_blocker=False,
            findings=[],
            metadata={
                "skipped": True,
                "reason": "Not applicable to this file type",
            },
        )
