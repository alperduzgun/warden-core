"""
Property Frame - Logic validation and invariants.

Validates business logic correctness:
- Function preconditions/postconditions
- Class invariants
- State machine transitions
- Mathematical properties

Priority: HIGH
"""

import re
import time
from typing import Any

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
    ValidationFrame,
)

logger = get_logger(__name__)


class PropertyFrame(ValidationFrame):
    """
    Property-based testing validation frame.

    This frame detects logic issues:
    - Missing precondition checks
    - Unvalidated state transitions
    - Invariant violations
    - Missing assertions
    - Logic inconsistencies

    Priority: HIGH
    Applicability: All languages
    """

    # Required metadata
    name = "Property Testing"
    description = "Validates business logic, invariants, and preconditions"
    category = FrameCategory.GLOBAL
    priority = FramePriority.HIGH
    scope = FrameScope.FILE_LEVEL
    is_blocker = False
    version = "1.0.0"
    author = "Warden Team"
    applicability = [FrameApplicability.ALL]

    # Property check patterns
    PATTERNS = {
        "division_no_zero_check": {
            "pattern": r"(?<!\/)\/\s*(\w+)(?!\s*(?:if|&&|\|\||\?|assert|\!=?\s*0))",
            "severity": "medium",
            "message": "Division operation without zero check",
            "suggestion": "Check divisor is not zero before division",
        },
        "comparison_always_true": {
            "pattern": r"if\s+true|if\s+True|while\s+true|while\s+True",
            "severity": "low",
            "message": "Always-true condition detected",
            "suggestion": "Review logic - condition always evaluates to true",
        },
        "negative_index_possible": {
            "pattern": r"\[\s*-?\w+\s*-\s*\w+\s*\]",
            "severity": "medium",
            "message": "Array access with possible negative index",
            "suggestion": "Ensure index is non-negative",
        },
    }

    SYSTEM_PROMPT = """You are an expert Formal Verification and Property Testing analyst. Analyze the provided code for logical errors, invariant violations, and precondition failures.

Focus on:
1. Invariant maintenance (class state consistency).
2. Precondition/Postcondition validation (contract violations).
3. Logical fallacies (always true/false conditions, dead code).
4. State machine transitions (illegal states, race conditions).
5. Mathematical properties (division by zero, overflow, precision loss).

Output must be a valid JSON object with the following structure:
{
    "score": <0-10 integer, 10 is verified>,
    "confidence": <0.0-1.0 float>,
    "summary": "<brief summary of findings>",
    "issues": [
        {
            "severity": "critical|high|medium|low",
            "category": "logic",
            "title": "<short title>",
            "description": "<detailed description>",
            "line": <line number>,
            "confidence": <0.0-1.0>,
            "evidenceQuote": "<exact code triggering issue>",
            "codeSnippet": "<surrounding code>"
        }
    ]
}"""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialize PropertyFrame."""
        super().__init__(config)

        # Pre-compile all patterns once for performance (KISS optimization)
        self._compiled_patterns = {
            check_id: {
                **check_config,
                "compiled": re.compile(check_config["pattern"]),
            }
            for check_id, check_config in self.PATTERNS.items()
        }

        # Pre-compile assertion check patterns
        self._assertion_pattern = re.compile(r"\bassert\b|Assert\.|assertThat")
        self._function_pattern = re.compile(r"def\s+\w+|function\s+\w+|public\s+\w+\s+\w+\(")

    async def execute_async(self, code_file: CodeFile) -> FrameResult:
        """
        Execute property testing checks on code file.

        Args:
            code_file: Code file to validate

        Returns:
            FrameResult with findings
        """
        start_time = time.perf_counter()

        logger.info(
            "property_frame_started",
            file_path=code_file.path,
            language=code_file.language,
        )

        findings = []

        # Run pattern-based checks using pre-compiled patterns
        for check_id, check_config in self._compiled_patterns.items():
            pattern_findings = self._check_pattern_compiled(
                code_file=code_file,
                check_id=check_id,
                compiled_pattern=check_config["compiled"],
                severity=check_config["severity"],
                message=check_config["message"],
                suggestion=check_config.get("suggestion"),
            )
            findings.extend(pattern_findings)

        # Run LLM analysis if available
        if hasattr(self, "llm_service") and self.llm_service:
            llm_findings = await self._analyze_with_llm(code_file)
            findings.extend(llm_findings)

        # Check for assertion usage (good practice)
        assertion_findings = self._check_assertions(code_file)
        findings.extend(assertion_findings)

        # Determine status
        status = self._determine_status(findings)

        duration = time.perf_counter() - start_time

        logger.info(
            "property_frame_completed",
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
                "checks_executed": len(self.PATTERNS) + 1,  # +1 for assertion check
                "file_size": code_file.size_bytes,
                "line_count": code_file.line_count,
            },
        )

    def _check_pattern_compiled(
        self,
        code_file: CodeFile,
        check_id: str,
        compiled_pattern: re.Pattern,
        severity: str,
        message: str,
        suggestion: str | None = None,
    ) -> list[Finding]:
        """Check for pattern matches in code using pre-compiled pattern."""
        findings: list[Finding] = []

        try:
            lines = code_file.content.split("\n")

            for line_num, line in enumerate(lines, start=1):
                # Skip comments
                if line.strip().startswith(("#", "//", "/*", "*")):
                    continue

                matches = compiled_pattern.finditer(line)
                for _ in matches:
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

    def _check_assertions(self, code_file: CodeFile) -> list[Finding]:
        """Check for missing assertions in critical code."""
        findings: list[Finding] = []

        # Count assertions vs functions using pre-compiled patterns
        assertion_count = len(self._assertion_pattern.findall(code_file.content))
        function_count = len(self._function_pattern.findall(code_file.content))

        # If many functions but no assertions, warn
        if function_count > 10 and assertion_count == 0:
            finding = Finding(
                id=f"{self.frame_id}-no-assertions",
                severity="low",
                message=f"File has {function_count} functions but no assertions",
                location=f"{code_file.path}:1",
                detail="Consider adding assertions or Pydantic validation to validate invariants and preconditions",
                code=None,
            )
            findings.append(finding)

        return findings

    def _determine_status(self, findings: list[Finding]) -> str:
        """Determine frame status based on findings."""
        if not findings:
            return "passed"

        # Count high severity
        high_count = sum(1 for f in findings if f.severity == "high")

        if high_count > 3:
            return "failed"  # Many high severity issues
        elif high_count > 0:
            return "warning"  # Some high severity
        else:
            return "passed"  # Only medium/low

    async def _analyze_with_llm(self, code_file: CodeFile) -> list[Finding]:
        """Analyze code using LLM for deeper property verification."""
        findings: list[Finding] = []
        try:
            import json

            from warden.llm.types import AnalysisResult, LlmRequest

            logger.info("property_llm_analysis_started", file=code_file.path)

            client = self.llm_service

            request = LlmRequest(
                system_prompt=self.SYSTEM_PROMPT,
                user_message=f"Analyze this {code_file.language} code:\n\n{code_file.content}",
                temperature=0.1,
                use_fast_tier=True,
            )

            response = await client.send_async(request)

            if response.success and response.content:
                # Handle markdown code blocks if present
                content = response.content
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[0].strip()

                try:
                    data = json.loads(content)
                    result = AnalysisResult.from_json(data)

                    for issue in result.issues:
                        findings.append(
                            Finding(
                                id=f"{self.frame_id}-llm-{issue.line}",
                                severity=issue.severity,
                                message=issue.title,
                                location=f"{code_file.path}:{issue.line}",
                                detail=issue.description,
                                code=issue.evidence_quote,
                            )
                        )

                    logger.info("property_llm_analysis_completed", findings=len(findings), confidence=result.confidence)

                except Exception as e:
                    logger.warning("property_llm_parsing_failed", error=str(e), content_preview=content[:100])
            else:
                logger.warning("property_llm_request_failed", error=response.error_message)

        except ImportError:
            logger.debug("property_llm_not_available")
        except Exception as e:
            logger.error("property_llm_error", error=str(e))

        return findings
