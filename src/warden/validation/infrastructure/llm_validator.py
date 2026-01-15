"""
LLM-based false positive detection for validation frames.

This module provides intelligent false positive detection using LLM analysis
to reduce noise in validation results.
"""

import json
from typing import Any, List, Optional
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

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count (approx 4 chars per token)."""
        return len(text) // 4

    async def batch_validate_async(
        self,
        findings: List[Finding],
        context: ValidationContext,
    ) -> List[tuple[Finding, bool, float, str]]:
        """
        Validate multiple findings in batch with token-aware chunking.
        """
        if not self._enabled or not findings:
            # If no LLM, accept all
            return [(f, True, 1.0, "No LLM validation available") for f in findings]

        results = []
        
        # Batch configuration
        MAX_TOKENS_PER_BATCH = 4000  # Safe limit for most models (leaving room for output)
        current_batch = []
        current_tokens = 0
        
        # Shared context token estimate
        context_str = f"{context.language} {context.framework} {context.project_type}"
        base_tokens = self._estimate_tokens(context_str) + 500  # +500 for prompt instructions

        for finding in findings:
            # Estimate tokens for this finding
            snippet = context.code_snippet # Note: This might be the whole file content?
            # Ideally context.code_snippet should be specific to the finding, but ValidationContext seems redundant?
            # Re-reading: ValidationContext is passed ONCE. Wait.
            # If ValidationContext is shared, it means `code_snippet` is the whole file?
            # If so, we are validating findings for the SAME file.
            
            # Finding usually has line info. We need to extract the specific snippet for the finding 
            # if we want to save tokens, OR we pass the file context once.
            
            # Let's assume finding has what we need or we use the snippet from context.
            # Actually, `ValidationContext` has `code_snippet`. If we are batching findings for the SAME file,
            # we don't need to repeat the code snippet for every finding if we structure the prompt right.
            # But wait, `batch_validate_async` takes `context`.
            
            # Let's assume we can put multiple findings in the prompt referring to the same code context.
            
            finding_tokens = self._estimate_tokens(f"{finding.rule_id} {finding.message}") + 50 
            
            if current_tokens + finding_tokens > MAX_TOKENS_PER_BATCH and current_batch:
                # Process current batch
                batch_results = await self._process_batch(current_batch, context)
                results.extend(batch_results)
                current_batch = []
                current_tokens = 0
            
            current_batch.append(finding)
            current_tokens += finding_tokens

        # Process remaining
        if current_batch:
             batch_results = await self._process_batch(current_batch, context)
             results.extend(batch_results)

        return results

    async def _process_batch(
        self, 
        batch: List[Finding], 
        context: ValidationContext
    ) -> List[tuple[Finding, bool, float, str]]:
        """Process a single batch of findings."""
        if not batch:
            return []
            
        try:
            prompt = self._build_batch_prompt(batch, context)
            
            response = await self.llm_service.analyze_with_context(
                prompt=prompt,
                context={
                    "file_path": context.file_path,
                    "language": context.language,
                }
            )
            
            parsed_results = self._parse_batch_response(response, batch)
            return parsed_results
            
        except Exception as e:
            logger.error("batch_validation_failed", error=str(e), file=context.file_path)
            # Fallback for entire batch
            return [(f, True, 0.5, f"Batch validation error: {str(e)}") for f in batch]

    def _build_batch_prompt(self, findings: List[Finding], context: ValidationContext) -> str:
        """Build prompt for multiple findings."""
        findings_json = []
        for f in findings:
            findings_json.append({
                "id": f.id, # usage of internal memory address ID if needed, or index
                "rule": f.rule_id,
                "message": f.message, # assuming .message exists
                "line": f.location.start_line if hasattr(f.location, 'start_line') else "unknown"
            })
            
        return f"""Analyze these {len(findings)} security findings for the SAME file.
Determine true/false positives.

CONTEXT:
File: {context.file_path}
Language: {context.language}
Framework: {context.framework or 'None'}
Project Type: {context.project_type}

CODE:
```{context.language}
{context.code_snippet}
```

FINDINGS TO ANALYZE:
{json.dumps(findings_json, indent=2)}

INSTRUCTIONS:
1. Analyze each finding against the code.
2. Check for test code, safe patterns, or mitigations.
3. Return a JSON object mapping finding IDs to results.

FORMAT:
{{
    "results": [
        {{
            "id": "finding_id_from_input",
            "is_valid": true/false,
            "confidence": 0.0-1.0,
            "reasoning": "Brief explanation"
        }}
    ]
}}
"""

    def _parse_batch_response(self, response: str, original_findings: List[Finding]) -> List[tuple[Finding, bool, float, str]]:
        try:
            # Extract JSON
            json_str = response
            if "{" in response:
                start = response.find("{")
                end = response.rfind("}") + 1
                json_str = response[start:end]
            
            data = json.loads(json_str)
            results_map = {str(r["id"]): r for r in data.get("results", [])}
            
            output = []
            for f in original_findings:
                # Match by ID (converted to str for consistency)
                res = results_map.get(str(f.id))
                if res:
                    output.append((
                        f, 
                        res.get("is_valid", True),
                        res.get("confidence", 0.5),
                        res.get("reasoning", "Batch analysis")
                    ))
                else:
                    # Missing in response, accept default
                    output.append((f, True, 0.5, "Missing from LLM batch response"))
            return output
            
        except Exception as e:
            logger.warning("batch_response_parse_failed", error=str(e))
            return [(f, True, 0.5, "Parse error") for f in original_findings]