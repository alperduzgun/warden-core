import json
from typing import List, Dict, Any, Optional
from warden.shared.infrastructure.logging import get_logger
from warden.llm.providers.base import ILlmClient
from warden.memory.application.memory_manager import MemoryManager
from warden.shared.utils.retry_utils import async_retry

logger = get_logger(__name__)

class FindingVerificationService:
    """
    Verifies findings using LLM to reduce false positives.
    Leverages Persistent Cache and Rate Limits.
    """

    DEFAULT_RETRIES = 3
    FALLBACK_CONFIDENCE = 0.5

    def __init__(
        self, 
        llm_client: ILlmClient, 
        memory_manager: Optional[MemoryManager] = None,
        enabled: bool = True
    ):
        self.llm = llm_client
        self.memory_manager = memory_manager
        self.enabled = enabled
        self.system_prompt = """
You are a Senior Code Auditor. Your task is to verify if a reported static analysis finding is a TRUE POSITIVE or a FALSE POSITIVE.

Input:
- Code Snippet: The code where the issue was found.
- Rule: The rule that was violated.
- Finding: The message reported by the tool.

Instructions:
1. Analyze the Context: Is this actual code or just a string/comment/stub?
2. Analyze the Logic: Does the code actually violate the rule in a dangerous way?
3. Ignore "Test" files unless the issue is critical.
4. Ignore "Type Hints" (e.g. Optional[str]) flagged as array access.
5. If a CRITICAL issue is in a 'test' file, classify it as False Positive (Intentional) unless it poses a risk to the production build or developer environment.

Return ONLY a JSON object:
{
    "is_true_positive": boolean,
    "confidence": float (0.0-1.0),
    "reason": "Short explanation why"
}
"""

    async def verify_findings(self, findings: List[Dict[str, Any]], context: Any = None) -> List[Dict[str, Any]]:
        """
        Filters out false positives from the findings list.
        Args:
            findings: List of raw findings
            context: PipelineContext object (optional but recommended)
        """
        if not self.enabled or not self.llm:
            return findings

        verified_findings = []
        
        # Only verify medium/high/critical. Low severity might be too noisy/expensive to verify all.
        # But for now, let's verify everything that looks programmatic (not just style).
        
        for finding in findings:
            # Skip if finding has no code context (cant verify)
            if not finding.get('location'):
                verified_findings.append(finding)
                continue

            # Generate Cache Key
            # Key = rule_id + code_hash (or code snippet)
            # We use the finding ID and code content as key
            cache_key = self._generate_key(finding)
            
            # 1. Check Cache
            cached_result = self._check_cache(cache_key)
            if cached_result:
                if cached_result.get('is_true_positive'):
                    finding['verification_metadata'] = cached_result
                    verified_findings.append(finding)
                else:
                    logger.debug("finding_verification_skipped_cached_false_positive", finding_id=finding.get('id'))
                continue

            # 2. Ask LLM
            try:
                result = await self._verify_with_llm(finding, context)
                
                # 3. Save Cache
                self._save_cache(cache_key, result)

                if result.get('is_true_positive'):
                    finding['verification_metadata'] = result
                    verified_findings.append(finding)
                else:
                    logger.info("finding_verification_rejected_false_positive", 
                                finding_id=finding.get('id'), 
                                reason=result.get('reason'))
            
            except Exception as e:
                logger.error("finding_verification_error", error=str(e), finding_id=finding.get('id'))
                # Fail open: If verification crashes, keep the finding to be safe
                verified_findings.append(finding)

        return verified_findings

    def _generate_key(self, finding: Dict[str, Any]) -> str:
        # Simple key generation
        import hashlib
        # Include rule, message, and specific location/code
        unique_str = f"{finding.get('id')}:{finding.get('code', '')}:{finding.get('location')}"
        return hashlib.sha256(unique_str.encode()).hexdigest()

    def _check_cache(self, key: str) -> Optional[Dict]:
        if self.memory_manager:
            return self.memory_manager.get_llm_cache(f"verify:{key}")
        return None

    def _save_cache(self, key: str, data: Dict) -> None:
        if self.memory_manager:
            self.memory_manager.set_llm_cache(f"verify:{key}", data)

    async def _verify_with_llm(self, finding: Dict[str, Any], context: Any = None) -> Dict:
        # Get Context Summary if available
        context_prompt = ""
        if context and hasattr(context, 'get_llm_context_prompt'):
             context_prompt = context.get_llm_context_prompt("VALIDATION")

        prompt = f"""
You are a Senior Security Engineer. Verify a potential finding in a specific project context.

PROJECT CONTEXT:
{context_prompt}

FINDING TO VERIFY:
- Rule ID: {finding.get('id')}
- Message: {finding.get('message')}
- File: {finding.get('location')}
- Code Snippet:
```
{finding.get('code', 'N/A')}
{finding.get('detail', '')}
```

STRATEGY:
1. ANALYZE FILE PURPOSE based on Path and Project Context:
   - TEST Context? -> Use LENIENT security rules. Allow mocks, hardcoded credentials (e.g. mock tokens).
   - SCRIPT/EXAMPLE? -> Use LENIENT rules.
   - PRODUCTION/CORE? -> Use STRICT rules.

2. ANALYZE CODE CONTEXT:
   - Is it a Type Hint (e.g. List[int])? -> REJECT (False Positive).
   - Is it a Comment/Docstring? -> REJECT.
   - Is it an Import statement? -> REJECT (unless malicious import).

3. DECISION:
   - Return true_positive: true ONLY if the code presents an ACTUAL RUNTIME RISK in this specific context.
"""
        # The caching logic is already handled in verify_findings,
        # so this method just focuses on the LLM call and parsing.
        result = await self._call_llm_with_retry(prompt)
        return result

    @async_retry(retries=DEFAULT_RETRIES)
    async def _call_llm_with_retry(self, prompt: str) -> Dict[str, Any]:
        """Call LLM with retry mechanism and parse response."""
        response = await self.llm.complete_async(prompt, self.system_prompt)
        
        try:
            # Parse JSON from response (handle markdown code blocks if present)
            content = response.content.strip()
            if content.startswith('```json'):
                content = content.replace('```json', '').replace('```', '')
            return json.loads(content)
        except Exception as e:
            logger.warning("llm_response_parsing_failed", error=str(e), response_content=response.content[:200])
            # Fallback if JSON parsing fails
            return {"is_true_positive": True, "confidence": self.FALLBACK_CONFIDENCE, "reason": "LLM response parsing failed"}

