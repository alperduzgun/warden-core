"""
Fuzz Frame - Edge case testing validation.

Tests code behavior with unexpected/malformed inputs:
- Boundary value testing
- Null/empty input handling
- Invalid data type handling
- Unicode/special character handling

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
from warden.llm.types import LlmRequest, AnalysisResult
from warden.llm.providers.base import ILlmClient

logger = get_logger(__name__)


class FuzzFrame(ValidationFrame):
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
            "pattern": r'\b(if|while)\s*\([^)]*\w+\s*[!=<>]+\s*[^)]*\)',
            "severity": "medium",
            "message": "Function may not handle null/None input",
            "suggestion": "Add null/None checks before using values",
        },
        "no_empty_string_check": {
            "pattern": r'(\.split\(|\.replace\(|\.substring\(|\.trim\()',
            "severity": "low",
            "message": "String operation without empty string check",
            "suggestion": "Check if string is empty before operations",
        },
        "array_access_no_bounds": {
            "pattern": r'\w+\[\w+\](?!\s*(?:if|&&|\|\|))',
            "severity": "medium",
            "message": "Array/list access without bounds checking",
            "suggestion": "Validate index is within bounds before access",
        },
        "type_conversion_no_validation": {
            "pattern": r'(int\(|float\(|parseInt\(|parseFloat\()',
            "severity": "medium",
            "message": "Type conversion without validation",
            "suggestion": "Wrap conversion in try-catch or validate input",
        },
    }

    SYSTEM_PROMPT = """You are an expert Fuzz Testing analyst. Analyze the provided code for edge cases, input validation vulnerabilities, and robustness issues.

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

    def __init__(self, config: Dict[str, Any] | None = None) -> None:
        """
        Initialize FuzzFrame.

        Args:
            config: Frame configuration
        """
        super().__init__(config)

    async def execute_batch(self, code_files: List[CodeFile]) -> List[FrameResult]:
        """
        Execute fuzz testing on multiple files.
        """
        # Serial execution for now to ensure reliability, bug fixes first.
        return await super().execute_batch(code_files)

    async def execute(self, code_file: CodeFile) -> FrameResult:
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

        # Run LLM analysis if available
        if hasattr(self, 'llm_service') and self.llm_service:
            llm_findings = await self._analyze_with_llm(code_file)
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
                # Skip comments (basic - language-agnostic)
                if line.strip().startswith(("#", "//", "/*", "*")):
                    continue

                matches = re.finditer(pattern, line)
                for match in matches:
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
    async def _analyze_with_llm(self, code_file: CodeFile) -> List[Finding]:
        """
        Analyze code using LLM for deeper fuzzing insights.
        """
        findings: List[Finding] = []
        try:
            logger.info("fuzz_llm_analysis_started", file=code_file.path)
            
            client: ILlmClient = self.llm_service
            
            request = LlmRequest(
                system_prompt=self.SYSTEM_PROMPT,
                user_message=f"Analyze this {code_file.language} code:\n\n{code_file.content}",
                temperature=0.1
            )
            
            response = await client.send_async(request)
            
            if response.success and response.content:
                # Parse JSON response
                import json
                
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
                        findings.append(Finding(
                            id=f"{self.frame_id}-llm-{issue.line}",
                            severity=issue.severity,
                            message=issue.title,
                            location=f"{code_file.path}:{issue.line}",
                            detail=issue.description,
                            code=issue.evidence_quote
                        ))
                    
                    logger.info("fuzz_llm_analysis_completed", 
                              findings=len(findings), 
                              confidence=result.confidence)
                              
                except Exception as e:
                    logger.warning("fuzz_llm_parsing_failed", error=str(e), content_preview=content[:100])
            else:
                 logger.warning("fuzz_llm_request_failed", error=response.error_message)

        except Exception as e:
            logger.error("fuzz_llm_error", error=str(e))
            
        return findings
