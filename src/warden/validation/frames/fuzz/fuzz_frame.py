"""
Fuzz Frame - Edge case testing validation.

Tests code behavior with unexpected/malformed inputs:
- Boundary value testing
- Null/empty input handling
- Invalid data type handling
- Unicode/special character handling

Priority: MEDIUM
"""

import re
import time
from typing import Any

from warden.llm.prompts.tool_instructions import get_tool_enhanced_prompt
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
from warden.validation.domain.mixins import TaintAware

logger = get_logger(__name__)


class FuzzFrame(ValidationFrame, TaintAware):
    """
    Fuzz testing validation frame.

    This frame detects missing edge case handling:
    - No null/None checks
    - Missing empty string validation
    - No boundary value checks
    - Missing type validation
    - Unhandled special characters

    Priority: MEDIUM
    Applicability: All languages
    """

    # Required metadata
    name = "Fuzz Testing"
    description = "Detects missing edge case handling (null, empty, boundaries, invalid types)"
    category = FrameCategory.GLOBAL
    priority = FramePriority.MEDIUM
    scope = FrameScope.FILE_LEVEL
    is_blocker = False
    version = "1.0.0"
    author = "Warden Team"
    applicability = [FrameApplicability.ALL]

    # Fuzz patterns (language-agnostic)
    PATTERNS = {
        "missing_null_check": {
            "pattern": r"\b(if|while)\s*\([^)]*\w+\s*[!=<>]+\s*[^)]*\)",
            "severity": "medium",
            "message": "Function may not handle null/None input",
            "suggestion": "Add null/None checks before using values",
        },
        "no_empty_string_check": {
            "pattern": r"(\.split\(|\.replace\(|\.substring\(|\.trim\()",
            "severity": "low",
            "message": "String operation without empty string check",
            "suggestion": "Check if string is empty before operations",
        },
        "array_access_no_bounds": {
            "pattern": r"\w+\[\w+\](?!\s*(?:if|&&|\|\|))",
            "severity": "medium",
            "message": "Array/list access without bounds checking",
            "suggestion": "Validate index is within bounds before access",
        },
        "type_conversion_no_validation": {
            "pattern": r"(int\(|float\(|parseInt\(|parseFloat\()",
            "severity": "medium",
            "message": "Type conversion without validation",
            "suggestion": "Wrap conversion in try-catch or validate input",
        },
    }

    _SYSTEM_PROMPT_BASE = """You are an expert Fuzz Testing analyst. Analyze the provided code for edge cases, input validation vulnerabilities, and robustness issues.

Focus exclusively on robustness against malformed/unexpected inputs:
1. Missing null/None/empty checks.
2. Boundary conditions (off-by-one, negative limits, max values).
3. Type confusion or unsafe conversions.
4. Check for unhandled exceptions during input parsing.
5. Resource exhaustion risks (large inputs).

Output must be a valid JSON object with the following structure:
{
    "score": <0-10 integer, 10 is secure>,
    "confidence": <0.0-1.0 float>,
    "summary": "<brief summary of findings>",
    "issues": [
        {
            "severity": "critical|high|medium|low",
            "category": "robustness",
            "title": "<short title>",
            "description": "<detailed description>",
            "line": <line number>,
            "confidence": <0.0-1.0>,
            "evidenceQuote": "<exact code triggering issue>",
            "codeSnippet": "<surrounding code>"
        }
    ]
}"""

    SYSTEM_PROMPT = get_tool_enhanced_prompt(_SYSTEM_PROMPT_BASE)

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """
        Initialize FuzzFrame.

        Args:
            config: Frame configuration
        """
        super().__init__(config)
        self._taint_paths: dict[str, list] = {}

    def set_taint_paths(self, taint_paths: dict[str, list]) -> None:
        """TaintAware implementation — receive shared taint analysis results."""
        self._taint_paths = taint_paths

    async def execute_async(self, code_file: CodeFile) -> FrameResult:
        """
        Execute fuzz testing checks on code file.

        Args:
            code_file: Code file to validate

        Returns:
            FrameResult with findings
        """
        start_time = time.perf_counter()

        logger.info(
            "fuzz_frame_started",
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

        # Boost taint source functions to HIGH priority fuzz targets
        file_taint_paths = self._taint_paths.get(code_file.path, [])
        if file_taint_paths:
            taint_source_lines: set[int] = set()
            for tp in file_taint_paths:
                if not tp.is_sanitized:
                    taint_source_lines.add(tp.source.line)
            for tp in file_taint_paths:
                if not tp.is_sanitized:
                    findings.append(
                        Finding(
                            id=f"{self.frame_id}-taint-fuzz-{tp.source.line}",
                            severity="high",
                            message=f"Taint source at line {tp.source.line} flows to {tp.sink.name} — high-priority fuzz target",
                            location=f"{code_file.path}:{tp.source.line}",
                            detail=f"Unsanitized data from {tp.source.name} reaches {tp.sink.name} [{tp.sink_type}]. "
                            f"Fuzz this input path with boundary values, null, and special characters.",
                            code=None,
                        )
                    )

        # Run LLM analysis if available
        if hasattr(self, "llm_service") and self.llm_service:
            llm_findings = await self._analyze_with_llm(code_file, file_taint_paths)
            findings.extend(llm_findings)

        # Determine status
        status = "passed" if len(findings) == 0 else "warning"

        duration = time.perf_counter() - start_time

        logger.info(
            "fuzz_frame_completed",
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
                "checks_executed": len(self.PATTERNS),
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
    ) -> list[Finding]:
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
        findings: list[Finding] = []

        try:
            lines = code_file.content.split("\n")

            for line_num, line in enumerate(lines, start=1):
                # Skip comments (basic - language-agnostic)
                if line.strip().startswith(("#", "//", "/*", "*")):
                    continue

                matches = re.finditer(pattern, line)
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

    async def _analyze_with_llm(self, code_file: CodeFile, taint_paths: list | None = None) -> list[Finding]:
        """
        Analyze code using LLM for deeper fuzzing insights.
        """
        findings: list[Finding] = []
        try:
            from warden.llm.types import AnalysisResult, LlmRequest

            logger.info("fuzz_llm_analysis_started", file=code_file.path)

            client = self.llm_service

            # Build taint context for LLM prompt
            taint_context = ""
            if taint_paths:
                unsanitized = [p for p in taint_paths if not p.is_sanitized]
                if unsanitized:
                    taint_context = "\n\n[TAINT ANALYSIS — Priority Fuzz Targets]:\n"
                    for tp in unsanitized[:5]:
                        taint_context += (
                            f"  - SOURCE: {tp.source.name} (line {tp.source.line})"
                            f" -> SINK: {tp.sink.name} [{tp.sink_type}] (line {tp.sink.line})\n"
                        )
                    taint_context += "Focus fuzz testing on these input paths.\n"

            from warden.shared.utils.llm_context import BUDGET_FUZZ, prepare_code_for_llm, resolve_token_budget

            budget = resolve_token_budget(BUDGET_FUZZ)
            truncated = prepare_code_for_llm(code_file.content, token_budget=budget)

            request = LlmRequest(
                system_prompt=self.SYSTEM_PROMPT,
                user_message=f"Analyze this {code_file.language} code:\n\n{truncated}{taint_context}",
                temperature=0.1,
            )

            response = await client.send_with_tools_async(request)

            if response.success and response.content:
                # Handle markdown code blocks if present
                content = response.content
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[0].strip()

                try:
                    # Parse result with Pydantic
                    result = AnalysisResult.from_json(content)

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

                    logger.info("fuzz_llm_analysis_completed", findings=len(findings), confidence=result.confidence)

                except Exception as e:
                    logger.warning("fuzz_llm_parsing_failed", error=str(e), content_preview=content[:100])
            else:
                logger.warning("fuzz_llm_request_failed", error=response.error_message)

        except ImportError:
            logger.debug("fuzz_llm_not_available")
        except Exception as e:
            logger.error("fuzz_llm_error", error=str(e))

        return findings
