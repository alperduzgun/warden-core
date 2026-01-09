import json
from typing import List, Dict, Any, Optional
from warden.shared.infrastructure.logging import get_logger
from warden.llm.providers.base import ILlmClient
from warden.memory.application.memory_manager import MemoryManager

logger = get_logger(__name__)

class FindingVerificationService:
    """
    Verifies findings using LLM to reduce false positives.
    Leverages Persistent Cache and Rate Limits.
    """

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

Return ONLY a JSON object:
{
    "is_true_positive": boolean,
    "confidence": float (0.0-1.0),
    "reason": "Short explanation why"
}
"""

    async def verify_findings(self, findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Filters out false positives from the findings list.
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
                result = await self._verify_with_llm(finding)
                
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

    async def _verify_with_llm(self, finding: Dict[str, Any]) -> Dict:
        prompt = f"""
Finding to Verify:
- Rule ID: {finding.get('id')}
- Message: {finding.get('message')}
- File: {finding.get('location')}
- Code Snippet:
```
{finding.get('code', 'N/A')}
{finding.get('detail', '')}
```
"""
        response = await self.llm.complete_async(prompt, self.system_prompt)
        
        # Parse JSON
        try:
            content = response.content.strip()
            if content.startswith('```json'):
                content = content.replace('```json', '').replace('```', '')
            return json.loads(content)
        except Exception as e:
            # Fallback if XML/JSON parsing fails
            return {"is_true_positive": True, "confidence": 0.5, "reason": "Parsing failed"}
