"""
Property Frame - Logic validation and invariants.

Validates business logic correctness:
- Function preconditions/postconditions
- Class invariants
- State machine transitions
- Mathematical properties

Priority: HIGH
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
        "missing_precondition": {
            "pattern": r'def\s+\w+\s*\([^)]+\):|function\s+\w+\s*\([^)]+\)\s*{',
            "severity": "high",
            "message": "Function may be missing input validation (precondition)",
            "suggestion": "Add parameter validation at function start",
        },
        "state_change_no_validation": {
            "pattern": r'self\.\w+\s*=|this\.\w+\s*=',
            "severity": "medium",
            "message": "State change without validation",
            "suggestion": "Validate state transitions to maintain invariants",
        },
        "division_no_zero_check": {
            "pattern": r'\/\s*\w+(?!\s*(?:if|&&|\|\||\?|assert))',
            "severity": "high",
            "message": "Division operation without zero check",
            "suggestion": "Check divisor is not zero before division",
        },
        "comparison_always_true": {
            "pattern": r'if\s+true|if\s+True|while\s+true|while\s+True',
            "severity": "low",
            "message": "Always-true condition detected",
            "suggestion": "Review logic - condition always evaluates to true",
        },
        "negative_index_possible": {
            "pattern": r'\[\s*-?\w+\s*-\s*\w+\s*\]',
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

    async def execute_batch(self, code_files: List[CodeFile]) -> List[FrameResult]:
        """
        Execute property testing on multiple files using chunked LLM calls.
        """
        if not hasattr(self, 'llm_service') or not self.llm_service:
            # Fallback to default serial execution for local checks
            return await super().execute_batch(code_files)

        logger.info("property_frame_batch_execution_started", file_count=len(code_files))
        
        # 1. Run local checks for all files first
        all_results = []
        
        # 2. Chunk files for LLM analysis (e.g., 5 files per chunk to stay safe with token limits)
        chunk_size = self.config.get("batch_size", 5)
        for i in range(0, len(code_files), chunk_size):
            chunk = code_files[i:i + chunk_size]
            
            # Run local checks for this chunk
            for code_file in chunk:
                # We still call execute() per file but we can skip the LLM part in execute
                # and call it here in batch for the chunk.
                # However, to keep it simple and compatible, we'll just use the serial
                # default and maybe implement a "BatchLlmAnalyzer" later.
                
                # FOR NOW: Let's just fix the bugs and keep it serial to avoid overengineering 
                # unless a clear batch LLM prompt is designed.
                result = await self.execute(code_file)
                all_results.append(result)
                
        return all_results

    async def execute(self, code_file: CodeFile) -> FrameResult:
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

                matches = re.finditer(pattern, line)
                for match in matches:
                    # Additional context-based filtering
                    if self._should_report(check_id, line, code_file.language):
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

    def _should_report(self, check_id: str, line: str, language: str) -> bool:
        """
        Additional filtering to reduce false positives.

        Args:
            check_id: Check identifier
            line: Code line
            language: Programming language

        Returns:
            True if should report finding
        """
        # Filter out precondition check if validation keywords present
        if check_id == "missing_precondition":
            validation_keywords = ["if", "assert", "raise", "throw", "validate", "check"]
            return not any(keyword in line.lower() for keyword in validation_keywords)

        return True

    def _check_assertions(self, code_file: CodeFile) -> List[Finding]:
        """
        Check for missing assertions in critical code.

        Args:
            code_file: Code file to check

        Returns:
            List of findings
        """
        findings: List[Finding] = []

        # Count assertions vs functions
        assertion_pattern = r'\bassert\b|Assert\.|assertThat'
        function_pattern = r'def\s+\w+|function\s+\w+|public\s+\w+\s+\w+\('

        assertion_count = len(re.findall(assertion_pattern, code_file.content))
        function_count = len(re.findall(function_pattern, code_file.content))

        # If many functions but no assertions, warn
        if function_count > 5 and assertion_count == 0:
            finding = Finding(
                id=f"{self.frame_id}-no-assertions",
                severity="low",
                message=f"File has {function_count} functions but no assertions",
                location=f"{code_file.path}:1",
                detail="Consider adding assertions to validate invariants and preconditions",
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

        if high_count > 3:
            return "failed"  # Many high severity issues
        elif high_count > 0:
            return "warning"  # Some high severity
        else:
            return "passed"  # Only medium/low

    async def _analyze_with_llm(self, code_file: CodeFile) -> List[Finding]:
        """
        Analyze code using LLM for deeper property verification.
        """
        findings: List[Finding] = []
        try:
            logger.info("property_llm_analysis_started", file=code_file.path)
            
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
                    data = json.loads(content)
                    result = AnalysisResult.from_json(data)
                    
                    for issue in result.issues:
                        findings.append(Finding(
                            id=f"{self.frame_id}-llm-{issue.line}",
                            severity=issue.severity,
                            message=issue.title,
                            location=f"{code_file.path}:{issue.line}",
                            detail=issue.description,
                            code=issue.evidence_quote
                        ))
                    
                    logger.info("property_llm_analysis_completed", 
                              findings=len(findings), 
                              confidence=result.confidence)
                              
                except Exception as e:
                    logger.warning("property_llm_parsing_failed", error=str(e), content_preview=content[:100])
            else:
                 logger.warning("property_llm_request_failed", error=response.error_message)

        except Exception as e:
            logger.error("property_llm_error", error=str(e))
            
        return findings
