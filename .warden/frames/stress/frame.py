"""
Stress Frame - Load and stress testing validation.

Validates code performance under load:
- Resource leaks (memory, files, connections)
- Inefficient algorithms (O(n²), nested loops)
- Missing caching
- Blocking operations in async code

Priority: MEDIUM
"""

import time
import re
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
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)


class StressFrame(ValidationFrame):
    """
    Stress testing validation frame.

    This frame detects performance issues:
    - Resource leaks (unclosed files/connections)
    - Inefficient algorithms (nested loops)
    - Missing pagination for large datasets
    - Blocking I/O in async contexts
    - Memory inefficient operations

    Priority: MEDIUM
    Applicability: All languages
    """

    # Required metadata
    name = "Stress Testing"
    description = "Detects performance issues, resource leaks, and inefficient algorithms"
    category = FrameCategory.GLOBAL
    priority = FramePriority.MEDIUM
    scope = FrameScope.FILE_LEVEL
    is_blocker = False
    version = "1.0.0"
    author = "Warden Team"
    applicability = [FrameApplicability.ALL]

    # Stress testing patterns
    PATTERNS = {
        "unclosed_file": {
            "pattern": r'open\(|File\(|FileReader\(|FileWriter\(',
            "severity": "high",
            "message": "File opened without context manager - potential resource leak",
            "suggestion": "Use 'with' statement (Python) or try-finally to ensure file closure",
        },
        "nested_loops": {
            "pattern": r'for\s+\w+\s+in.*:\s*\n\s+for\s+\w+\s+in',
            "severity": "medium",
            "message": "Nested loops detected - O(n²) complexity",
            "suggestion": "Consider using dictionary/set for O(1) lookup or optimizing algorithm",
        },
        "blocking_in_async": {
            "pattern": r'async\s+def\s+\w+.*(?:open\(|requests\.get|time\.sleep)',
            "severity": "high",
            "message": "Blocking operation in async function",
            "suggestion": "Use async I/O (aiofiles, httpx, asyncio.sleep) instead",
        },
        "no_pagination": {
            "pattern": r'\.all\(\)|SELECT \* FROM|find\(\{',
            "severity": "medium",
            "message": "Query fetching all records - missing pagination",
            "suggestion": "Add limit/offset or cursor-based pagination for large datasets",
        },
        "string_concatenation_loop": {
            "pattern": r'for\s+.*:\s*\n\s+\w+\s*\+=\s*["\']',
            "severity": "medium",
            "message": "String concatenation in loop - inefficient",
            "suggestion": "Use list and join() (Python) or StringBuilder (Java/C#)",
        },
        "global_state_mutation": {
            "pattern": r'global\s+\w+|var\s+\w+\s*=|let\s+\w+\s*=.*(?:window|document)',
            "severity": "low",
            "message": "Global state mutation detected",
            "suggestion": "Minimize global state - can cause issues under load",
        },
    }

    def __init__(self, config: Dict[str, Any] | None = None) -> None:
        """
        Initialize StressFrame.

        Args:
            config: Frame configuration
        """
        super().__init__(config)

    async def execute(self, code_file: CodeFile) -> FrameResult:
        """
        Execute stress testing checks on code file.

        Args:
            code_file: Code file to validate

        Returns:
            FrameResult with findings
        """
        start_time = time.perf_counter()

        logger.info(
            "stress_frame_started",
            file_path=code_file.path,
            language=code_file.language,
        )

        findings = []

        # Run pattern-based checks
        for check_id, check_config in self.PATTERNS.items():
            pattern_findings = self._check_pattern(
                code_file=code_file,
                check_id=check_id,
                pattern=check_config["pattern"],
                severity=check_config["severity"],
                message=check_config["message"],
                suggestion=check_config.get("suggestion"),
            )
            findings.extend(pattern_findings)

        # Check file size (large files may need optimization)
        size_findings = self._check_file_size(code_file)
        findings.extend(size_findings)

        # Determine status
        status = self._determine_status(findings)

        duration = time.perf_counter() - start_time

        logger.info(
            "stress_frame_completed",
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
            is_blocker=False,
            findings=findings,
            metadata={
                "checks_executed": len(self.PATTERNS) + 1,  # +1 for file size check
                "file_size": code_file.size_bytes,
                "line_count": code_file.line_count,
            },
        )

    def _check_pattern(
        self,
        code_file: CodeFile,
        check_id: str,
        pattern: str,
        severity: str,
        message: str,
        suggestion: str | None = None,
    ) -> List[Finding]:
        """
        Check for pattern matches in code.

        Args:
            code_file: Code file to check
            check_id: Unique check identifier
            pattern: Regex pattern to match
            severity: Finding severity
            message: Finding message
            suggestion: Optional suggestion

        Returns:
            List of findings
        """
        findings: List[Finding] = []

        try:
            lines = code_file.content.split("\n")

            for line_num, line in enumerate(lines, start=1):
                # Skip comments
                if line.strip().startswith(("#", "//", "/*", "*")):
                    continue

                matches = re.finditer(pattern, line, re.MULTILINE)
                for match in matches:
                    # Context-based filtering
                    if self._should_report(check_id, line, lines, line_num):
                        finding = Finding(
                            id=f"{self.frame_id}-{check_id}-{line_num}",
                            severity=severity,
                            message=message,
                            location=f"{code_file.path}:{line_num}",
                            detail=suggestion,
                            code=line.strip(),
                        )
                        findings.append(finding)

        except Exception as e:
            logger.error(
                "pattern_check_failed",
                check_id=check_id,
                error=str(e),
            )

        return findings

    def _should_report(
        self, check_id: str, line: str, all_lines: List[str], line_num: int
    ) -> bool:
        """
        Additional filtering to reduce false positives.

        Args:
            check_id: Check identifier
            line: Code line
            all_lines: All file lines
            line_num: Current line number

        Returns:
            True if should report finding
        """
        # For unclosed_file, check if 'with' statement is used
        if check_id == "unclosed_file":
            # Look ahead for 'with' keyword
            context = " ".join(all_lines[max(0, line_num - 2) : line_num + 2])
            if "with" in context:
                return False

        # For nested_loops, only report if really nested (basic check)
        if check_id == "nested_loops":
            # This is a simplified check - could be enhanced
            return "for" in line and line_num < len(all_lines) - 1

        return True

    def _check_file_size(self, code_file: CodeFile) -> List[Finding]:
        """
        Check if file is too large (potential maintainability issue).

        Args:
            code_file: Code file to check

        Returns:
            List of findings
        """
        findings: List[Finding] = []

        # File size threshold: 500 lines (from warden_core_rules.md)
        if code_file.line_count > 500:
            finding = Finding(
                id=f"{self.frame_id}-file-too-large",
                severity="medium",
                message=f"File has {code_file.line_count} lines (exceeds 500 line limit)",
                location=f"{code_file.path}:1",
                detail="Large files are harder to maintain and test. Consider splitting into modules.",
                code=None,
            )
            findings.append(finding)

        return findings

    def _determine_status(self, findings: List[Finding]) -> str:
        """
        Determine frame status based on findings.

        Args:
            findings: All findings

        Returns:
            Status: 'passed', 'warning', or 'failed'
        """
        if not findings:
            return "passed"

        # Count high severity
        high_count = sum(1 for f in findings if f.severity == "high")

        if high_count > 2:
            return "failed"  # Multiple resource leaks or blocking I/O
        elif high_count > 0:
            return "warning"  # Some high severity issues
        else:
            return "passed"  # Only medium/low
