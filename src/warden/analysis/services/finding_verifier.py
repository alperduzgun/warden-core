import json
import os
import re
from typing import Any

import psutil

from warden.llm.providers.base import ILlmClient
from warden.memory.application.memory_manager import MemoryManager
from warden.shared.infrastructure.logging import get_logger
from warden.shared.utils.finding_utils import get_finding_attribute
from warden.shared.utils.retry_utils import async_retry

logger = get_logger(__name__)


class FindingVerificationService:
    """
    Verifies findings using LLM to reduce false positives.
    Leverages Persistent Cache and Rate Limits.
    """

    DEFAULT_RETRIES = 3
    FALLBACK_CONFIDENCE = 0.5

    def _get(self, obj: Any, key: str, default: Any = None) -> Any:
        """Helper to get values from Finding objects or dicts (Deprecated: Use finding_utils)."""
        return get_finding_attribute(obj, key, default)

    def _set(self, obj: Any, key: str, value: Any) -> None:
        """Helper to set values on Finding objects or dicts (Deprecated: Use finding_utils)."""
        from warden.shared.utils.finding_utils import set_finding_attribute

        set_finding_attribute(obj, key, value)

    def __init__(self, llm_client: ILlmClient, memory_manager: MemoryManager | None = None, enabled: bool = True):
        self.llm = llm_client
        self.memory_manager = memory_manager
        self.enabled = enabled

        # Detect Local LLM (Ollama / Local HTTP)
        provider = str(getattr(llm_client, "provider", "")).upper()
        endpoint = str(getattr(llm_client, "endpoint", getattr(llm_client, "_endpoint", "")))
        self.is_local = (
            "OLLAMA" in provider
            or "localhost" in endpoint
            or "127.0.0.1" in endpoint
            or "::1" in endpoint
            or "0:0:0:0:0:0:0:1" in endpoint
        )

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

    async def verify_findings_async(self, findings: list[dict[str, Any]], context: Any = None) -> list[dict[str, Any]]:
        """
        Filters out false positives from the findings list using:
        Heuristic Filter -> Cache -> Batch LLM Verification.
        """
        if not self.enabled or not self.llm:
            return findings

        initial_count = len(findings)
        verified_findings = []
        candidates_to_verify = []

        # STEP 1: Heuristic Speed Layer (Alpha Filter)
        # Discard obvious false positives without hitting cache or LLM
        for finding in findings:
            if not self._get(finding, "location"):
                verified_findings.append(finding)
                continue

            code_snippet = (self._get(finding, "code") or "").strip()

            # Skip verification for Linter findings (User request: Don't waste tokens on linters)
            detail = self._get(finding, "detail") or ""
            if "(Ruff)" in detail or self._get(finding, "id", "").startswith("lint_"):
                # Mark as verified with high confidence without LLM
                self._set(finding, "confidence", 1.0)
                self._set(finding, "is_true_positive", True)
                self._set(finding, "verification_source", "linter_deterministic")
                verified_findings.append(finding)
                continue

            if self._is_obvious_false_positive(finding, code_snippet):
                logger.info(
                    "heuristic_filter_rejected_finding",
                    finding_id=self._get(finding, "id"),
                    rule=self._get(finding, "rule_id"),
                )
                continue

            candidates_to_verify.append(finding)

        if not candidates_to_verify:
            return verified_findings

        # STEP 2: Cache Check
        remaining_after_cache = []
        for finding in candidates_to_verify:
            cache_key = self._generate_key(finding)
            cached_result = self._check_cache(cache_key)

            if cached_result:
                # SAFE ACCESS: cached_result might be a dict or potentially an object from older cache
                self._set(cached_result, "cached", True)
                if self._get(cached_result, "is_true_positive", True):
                    self._set(finding, "verification_metadata", cached_result)
                    verified_findings.append(finding)
                continue

            remaining_after_cache.append(finding)

        if not remaining_after_cache:
            return verified_findings

        # STEP 3: Batch LLM Verification
        requested_batch_size = 10
        logger.info("batch_verification_starting", count=len(remaining_after_cache))

        i = 0
        while i < len(remaining_after_cache):
            # Dynamic resource-check
            batch_size = self._get_safe_batch_size(requested_batch_size)
            batch = remaining_after_cache[i : i + batch_size]

            try:
                batch_results = await self._verify_batch_with_llm_async(batch, context)

                for idx, result in enumerate(batch_results):
                    finding = batch[idx]
                    cache_key = self._generate_key(finding)
                    self._save_cache(cache_key, result)

                    # SAFE ACCESS: result might be a dict or object depending on LLM response/mock
                    is_tp = self._get(result, "is_true_positive", True)

                    if is_tp:
                        self._set(finding, "verification_metadata", result)
                        verified_findings.append(finding)
                    # Rejected findings logged in verification_summary below
            except Exception as e:
                logger.error("batch_verification_failed_manual_review_needed", error=str(e))
                # Fallback: Mark for manual review instead of failing open blindly
                for finding in batch:
                    self._set(
                        finding,
                        "verification_metadata",
                        {
                            "is_true_positive": True,  # Still include but flag it
                            "confidence": self.FALLBACK_CONFIDENCE,
                            "reason": f"Fallback: LLM Unavailable ({e!s}). Manual Verification Required.",
                            "review_required": True,
                            "fallback": True,
                        },
                    )
                verified_findings.extend(batch)

            i += len(batch)

        logger.info(
            "verification_summary",
            initial=initial_count,
            final=len(verified_findings),
            reduction=f"{((initial_count - len(verified_findings)) / initial_count) * 100:.1f}%"
            if initial_count > 0
            else "0%",
        )

        return verified_findings

    def _is_obvious_false_positive(self, finding: Any, code: str) -> bool:
        """Heuristic Alpha Filter to detect obvious false positives instantly."""
        # 1. Comment/Docstring check (ENHANCED)
        message_lower = (self._get(finding, "message") or "").lower()
        location_lower = (self._get(finding, "location") or "").lower()

        # Direct comment/docstring markers
        if code.startswith(("#", "//", "/*", '"""', "'''")) or "docstring" in message_lower:
            return True

        # Enhanced docstring detection - check for docstring keywords and patterns
        docstring_indicators = [
            "Example:",
            "Examples:",
            "Args:",
            "Returns:",
            "Raises:",
            "Note:",
            "Warning:",
            "See also:",
            '"""',
            "'''",
            "# Example",
            "# Usage",
        ]

        if any(indicator in code for indicator in docstring_indicators):
            return True

        # Check if location suggests it's in a docstring (e.g., line appears to be documentation)
        if "check_loader" in location_lower and "example" in code.lower():
            return True

        # 2. Type Hint check (common FP in Python/TS)
        # e.g. "Optional[str]", "List[int]"
        if "[" in code and "]" in code and "(" not in code:
            if any(t in code for t in ["Optional", "List", "Dict", "Union", "Any"]):
                return True

        # 3. Import check
        if code.startswith(("import ", "from ", "require(")):
            return True

        # 4. Dummy/Example data in Test files
        location = (self._get(finding, "location") or "").lower()
        if ("test" in location or "example" in location) and any(
            d in code.lower() for d in ["dummy", "mock", "fake", "test_password", "secret123"]
        ):
            return True

        # 5. Pattern definition detection (NEW)
        # Check if code is in a pattern definition list/tuple
        if self._is_pattern_definition(code, finding):
            logger.debug("fp_pattern_definition", finding_id=self._get(finding, "id"), code_preview=code[:50])
            return True

        return False

    def _is_pattern_definition(self, code: str, finding: Any) -> bool:
        """
        Detect if finding is in a security pattern definition list.

        Pattern definitions are lists/tuples of security patterns used by
        validation checks themselves (not actual dangerous code usage).

        Examples:
            ("eval", "Code execution", "critical")
            (r"api_key\\s*=", "Hardcoded API key")
        """
        self._get(finding, "id", "")

        # Look for common pattern definition structures
        pattern_indicators = [
            # Tuple/list of (pattern, description, severity)
            r'\(".*?",\s*".*?",\s*".*?"\)',
            # Tuple/list of (pattern, description)
            r'\(".*?",\s*".*?"\)',
            r'\(r".*?",\s*".*?"\)',  # Raw string patterns
            # Variable names suggesting pattern definitions
            r"(security_patterns|dangerous_funcs|risky_calls|check_patterns|patterns|secret_patterns)",
            # Assignment to pattern lists
            r"patterns\s*=\s*\[",
            r"DANGEROUS_PATTERNS\s*=",
            r"SECRET_PATTERNS\s*=",
            # Common in security check definitions
            r"PASSWORD_KEYWORDS\s*=",
            r"COMMON_PASSWORDS\s*=",
        ]

        for indicator in pattern_indicators:
            if re.search(indicator, code, re.IGNORECASE):
                # Additionally check if the code snippet is surrounded by quotes and commas
                # This indicates it's a string literal in a data structure

                # Check for tuple pattern: ("eval(", "description", "severity"),
                if re.search(r'^\s*\(["\']', code.strip()) and re.search(r'["\'],?\s*\),?\s*$', code.strip()):
                    # Count commas to confirm it's a multi-element tuple (pattern definition)
                    if code.count(",") >= 2:
                        return True

                # Check for string literal patterns: "eval", 'password', etc.
                if re.search(r'^["\'][^"\']+["\'],?\s*$', code.strip()):
                    return True

        return False

    @async_retry(retries=2, initial_delay=1.0, backoff_factor=2.0)
    async def _verify_batch_with_llm_async(
        self, batch: list[dict[str, Any]], context: Any = None
    ) -> list[dict[str, Any]]:
        """Verifies a batch of findings in a single LLM request."""
        context_prompt = ""
        if context and hasattr(context, "get_llm_context_prompt"):
            context_prompt = context.get_llm_context_prompt("VALIDATION")

        findings_summary = ""
        for i, f in enumerate(batch):
            try:
                # SAFE ACCESS: Use internal helper to handle dict vs object
                f_id = self._get(f, "id", "unknown")
                f_rule = self._get(f, "rule_id", "unknown")
                f_msg = self._get(f, "message", "unknown")
                f_code = self._get(f, "code", "N/A")

                findings_summary += f"""
FINDING #{i}:
- ID: {f_id}
- Rule: {f_rule}
- Message: {f_msg}
- Code: `{f_code}`
"""
            except Exception as e:
                import traceback

                logger.error("VERIFIER_BATCH_ITEM_PROCESSING_FAILED", error=str(e), trace=traceback.format_exc())
                continue

        prompt = f"""
You are a Senior Security Engineer. Verify a BATCH of {len(batch)} potential findings.
For each finding, determine if it is a TRUE POSITIVE (actual runtime risk) or FALSE POSITIVE.

PROJECT CONTEXT:
{context_prompt}

BATCH TO VERIFY:
{findings_summary}

DECISION RULES:
1. REJECT if code is a Type Hint, Comment, or Import.
2. REJECT if in a TEST file/context unless it's an extreme risk.
3. ACCEPT only if the code actually performs a dangerous operation or leaks sensitive production data.

Return ONLY a JSON array of objects in the EXACT order:
[
  {{"idx": 0, "is_true_positive": bool, "confidence": float, "reason": "..."}},
  ...
]
"""
        # Call LLM
        model = None
        if context and hasattr(context, "llm_config") and context.llm_config:
            model = getattr(context.llm_config, "smart_model", None)

        response = await self.llm.complete_async(prompt, self.system_prompt, model=model, use_fast_tier=True)

        try:
            if not response.success or not response.content:
                raise ValueError(f"LLM request failed: {response.error_message}")

            content = response.content.strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].strip()

            results = json.loads(content)
            # Ensure results match batch size and are in order (or mapped by idx)
            # For simplicity, we trust the LLM order but could sort by 'idx' if needed
            return results
        except Exception as e:
            logger.warning("batch_llm_parsing_failed", error=str(e))
            # Fallback: Mark for manual review due to parsing error
            return [
                {
                    "is_true_positive": True,
                    "confidence": 0.4,  # Slightly lower confidence for parse errors
                    "reason": "LLM responded but output parsing failed. Manual Review recommended.",
                    "review_required": True,
                }
                for _ in batch
            ]

    def _generate_key(self, finding: Any) -> str:
        import hashlib

        # Safe access using internal helper
        loc = self._get(finding, "location") or ""
        finding_id = self._get(finding, "id")
        code = self._get(finding, "code") or ""

        unique_str = f"{finding_id}:{code}:{loc}"
        return hashlib.sha256(unique_str.encode()).hexdigest()

    def _check_cache(self, key: str) -> dict | None:
        try:
            if self.memory_manager:
                return self.memory_manager.get_llm_cache(f"verify:{key}")
        except Exception as e:
            logger.warning("cache_lookup_failed", key=key, error=str(e))
        return None

    def _save_cache(self, key: str, data: dict) -> None:
        try:
            if self.memory_manager:
                self.memory_manager.set_llm_cache(f"verify:{key}", data)
        except Exception as e:
            logger.warning("cache_save_failed", key=key, error=str(e))

    def _get_safe_batch_size(self, max_allowed: int) -> int:
        """Adaptive batch size based on RAM/CPU."""
        if not getattr(self, "is_local", False):
            return max_allowed
        try:
            mem = psutil.virtual_memory()
            available_gb = mem.available / (1024**3)
            mem_limit = max(1, int(available_gb // 2.5))  # Verification is heavy, 2.5GB per item

            cpu_load = psutil.cpu_percent(interval=None)
            cpu_limit = 1 if cpu_load > 85 else max_allowed

            return min(max_allowed, mem_limit, cpu_limit, (os.cpu_count() or 2) // 2)
        except (AttributeError, psutil.Error, OSError):
            # psutil unavailable or error - default to safe value
            return 1
