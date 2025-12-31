"""
LLM-based false positive detection for validation frames.

This module provides intelligent false positive detection using LLM analysis
to reduce noise in validation results.
"""

import json
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
import structlog

from warden.validation.domain.frame import Finding

# Optional LLM service - will be None if not available
try:
    from warden.llm.application.llm_service import LLMService
except ImportError:
    LLMService = None

logger = structlog.get_logger()


@dataclass
class ValidationContext:
    """Context for validation decision making."""

    file_path: str
    language: str
    framework: Optional[str]
    project_type: str
    code_snippet: str
    rule_id: str
    rule_message: str
    severity: str


class LLMValidator:
    """
    Intelligent validation using LLM for false positive detection.

    Reduces validation noise by:
    1. Analyzing context around findings
    2. Understanding code intent
    3. Detecting test/example code
    4. Recognizing framework patterns
    """

    def __init__(self, llm_service: Optional[Any] = None):
        """Initialize with LLM service."""
        self.llm_service = llm_service
        self._enabled = llm_service is not None

    async def validate_finding_async(
        self,
        finding: Finding,
        context: ValidationContext,
    ) -> tuple[bool, float, str]:
        """
        Validate if a finding is a true positive or false positive.

        Args:
            finding: The validation finding to check
            context: Additional context for decision making

        Returns:
            Tuple of (is_valid, confidence, reasoning)
            - is_valid: True if this is a real issue, False if false positive
            - confidence: 0.0 to 1.0 confidence score
            - reasoning: Explanation of the decision
        """
        if not self._enabled:
            # No LLM available, accept all findings
            return True, 1.0, "No LLM validation available"

        try:
            # Build prompt for false positive detection
            prompt = self._build_validation_prompt(finding, context)

            # Get LLM analysis
            response = await self.llm_service.analyze_with_context(
                prompt=prompt,
                context={
                    "file_path": context.file_path,
                    "language": context.language,
                    "framework": context.framework,
                    "project_type": context.project_type,
                }
            )

            # Parse LLM response
            return self._parse_validation_response(response)

        except Exception as e:
            logger.warning(
                "llm_validation_failed",
                finding_id=finding.id,
                error=str(e),
            )
            # On error, accept the finding
            return True, 0.5, f"LLM validation error: {str(e)}"

    def _build_validation_prompt(
        self,
        finding: Finding,
        context: ValidationContext,
    ) -> str:
        """Build prompt for false positive detection."""
        return f"""Analyze if this security finding is a true positive or false positive.

CONTEXT:
- File: {context.file_path}
- Language: {context.language}
- Framework: {context.framework or 'None'}
- Project Type: {context.project_type}

FINDING:
- Rule: {context.rule_id}
- Message: {context.rule_message}
- Severity: {context.severity}
- Location: {finding.location}

CODE:
```{context.language}
{context.code_snippet}
```

ANALYSIS REQUIRED:
1. Is this a real security issue or a false positive?
2. Consider:
   - Is this test/example code?
   - Is the pattern safe in this framework context?
   - Are there mitigating factors (validation, sanitization)?
   - Is the severity appropriate?

Respond in JSON format:
{{
    "is_valid": true/false,
    "confidence": 0.0-1.0,
    "reasoning": "Brief explanation",
    "mitigations_found": ["list", "of", "mitigations"],
    "recommended_severity": "critical|high|medium|low|info"
}}"""

    def _parse_validation_response(self, response: str) -> tuple[bool, float, str]:
        """Parse LLM validation response."""
        try:
            # Try to parse JSON response
            if "{" in response and "}" in response:
                # Extract JSON from response
                json_start = response.index("{")
                json_end = response.rindex("}") + 1
                json_str = response[json_start:json_end]

                result = json.loads(json_str)

                return (
                    result.get("is_valid", True),
                    result.get("confidence", 0.5),
                    result.get("reasoning", "No reasoning provided"),
                )
        except (json.JSONDecodeError, ValueError) as e:
            logger.debug("llm_response_parse_error", error=str(e))

        # Fallback: Accept finding if can't parse
        return True, 0.5, "Could not parse LLM response"

    async def batch_validate_async(
        self,
        findings: List[Finding],
        context: ValidationContext,
    ) -> List[tuple[Finding, bool, float, str]]:
        """
        Validate multiple findings in batch.

        Args:
            findings: List of findings to validate
            context: Shared context for all findings

        Returns:
            List of tuples (finding, is_valid, confidence, reasoning)
        """
        results = []

        for finding in findings:
            is_valid, confidence, reasoning = await self.validate_finding_async(
                finding, context
            )
            results.append((finding, is_valid, confidence, reasoning))

        return results

    async def filter_false_positives_async(
        self,
        findings: List[Finding],
        context: ValidationContext,
        confidence_threshold: float = 0.7,
    ) -> List[Finding]:
        """
        Filter out false positives from findings list.

        Args:
            findings: Original findings list
            context: Validation context
            confidence_threshold: Minimum confidence to keep finding

        Returns:
            Filtered list with false positives removed
        """
        if not self._enabled:
            return findings

        validated = await self.batch_validate_async(findings, context)

        filtered = []
        for finding, is_valid, confidence, reasoning in validated:
            if is_valid and confidence >= confidence_threshold:
                # Keep true positives with high confidence
                filtered.append(finding)
            else:
                # Log filtered false positives
                logger.info(
                    "false_positive_filtered",
                    finding_id=finding.id,
                    confidence=confidence,
                    reasoning=reasoning,
                )

        logger.info(
            "false_positive_filtering_complete",
            original_count=len(findings),
            filtered_count=len(filtered),
            removed_count=len(findings) - len(filtered),
        )

        return filtered