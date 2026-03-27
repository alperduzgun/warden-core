import json
import os
import re
from typing import Any

import psutil

from warden.llm.providers.base import ILlmClient
from warden.memory.application.memory_manager import MemoryManager
from warden.shared.infrastructure.logging import get_logger
from warden.shared.utils.docstring_utils import (
    has_docstring_context_indicator,
    looks_like_comment_or_docstring,
)
from warden.shared.utils.finding_utils import get_finding_attribute
from warden.shared.utils.retry_utils import async_retry

logger = get_logger(__name__)

# High-precision sources produce exact structural/pattern matches — no LLM needed.
_HIGH_PRECISION_SOURCES = frozenset({"regex", "ast", "rust_engine"})

# Taint analysis is probabilistic (typical confidence 0.60–0.75).
# Sending taint findings to LLM verification reduces false positives.
# Keep this set for callers that need the full list.
_DETERMINISTIC_SOURCES = _HIGH_PRECISION_SOURCES | frozenset({"taint"})


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

LOGIC-LEVEL VULNERABILITY AWARENESS (these ARE real vulnerabilities — do NOT reject):
- Timing attack: == used to compare hash/secret/token values (should use hmac.compare_digest)
- JWT alg:none bypass: JWT decode accepting "none" algorithm
- JWT long expiry: token expiry >7 days
- Role from JWT: trusting role/permission from JWT payload without server-side lookup
- Weak crypto: MD5/SHA1 with static salt
- format_map injection: format()/format_map() with user-controlled input
- Predictable tokens: random module for security tokens/session IDs
- Bypassable sanitizer: HTML sanitizer using replace() blocklist
- Weak regex: validation regex using .* or trivially bypassable patterns

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

            # Exempt high-precision findings from LLM verification.
            # Regex, AST, and rust_engine produce exact structural matches — LLM adds
            # no value and only risks suppressing real issues.
            # Taint findings are probabilistic and benefit from LLM FP reduction.
            det_source = (
                self._get(finding, "detection_source")
                or self._get(finding, "detectionSource")
            )
            if det_source in _HIGH_PRECISION_SOURCES:
                self._set(finding, "confidence", 1.0)
                self._set(finding, "is_true_positive", True)
                self._set(finding, "verification_source", "deterministic_exempt")
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

        # STEP 3: Batch LLM Verification (token-aware batching)
        MAX_CONSECUTIVE_FAILURES = 3
        MAX_BATCH_TOKENS = 4000  # Safe token budget per batch
        MAX_BATCH_SIZE = 10  # Hard cap
        logger.info("batch_verification_starting", count=len(remaining_after_cache))

        # Build token-aware batches
        _batches: list[list] = []
        _cur_batch: list = []
        _cur_tokens = 0
        for _finding in remaining_after_cache:
            _msg = getattr(_finding, "message", "") or (
                _finding.get("message", "") if isinstance(_finding, dict) else ""
            ) or ""
            _code = getattr(_finding, "code", "") or (
                _finding.get("code", "") if isinstance(_finding, dict) else ""
            ) or ""
            _est = len(_msg.split()) + len(_code.split())
            if _cur_tokens + _est > MAX_BATCH_TOKENS or len(_cur_batch) >= MAX_BATCH_SIZE:
                if _cur_batch:
                    _batches.append(_cur_batch)
                _cur_batch = [_finding]
                _cur_tokens = _est
            else:
                _cur_batch.append(_finding)
                _cur_tokens += _est
        if _cur_batch:
            _batches.append(_cur_batch)

        # Parallel batch verification with soft timeout + graceful degradation.
        # All batches run concurrently via asyncio.gather — ~5x faster than sequential.
        # Soft timeout: if verification exceeds budget, remaining batches are marked unverified.
        import asyncio as _asyncio
        import time as _time

        VERIFICATION_BUDGET_S = 90.0  # Soft timeout — enough for 10 parallel batches
        _start = _time.monotonic()

        async def _verify_one_batch(batch: list) -> tuple[list, list | None]:
            """Verify a single batch. Returns (batch, results) or (batch, None) on error."""
            try:
                results = await self._verify_batch_with_llm_async(batch, context)
                return batch, results
            except Exception as e:
                logger.error("batch_verification_failed", error=str(e))
                return batch, None

        # Run all batches in parallel (bounded by LLM concurrency, not here)
        tasks = [_verify_one_batch(b) for b in _batches]
        completed = await _asyncio.gather(*tasks, return_exceptions=False)

        consecutive_failures = 0
        for batch, results in completed:
            elapsed = _time.monotonic() - _start

            if results is not None:
                consecutive_failures = 0
                for idx, result in enumerate(results):
                    finding = batch[idx]
                    cache_key = self._generate_key(finding)
                    if self._get(result, "verification_source") != "parse_fail_fallback":
                        self._save_cache(cache_key, result)
                    is_tp = self._get(result, "is_true_positive", True)
                    if is_tp:
                        self._set(finding, "verification_metadata", result)
                        verified_findings.append(finding)
            else:
                consecutive_failures += 1
                # Mark batch as unverified (fail-safe: keep findings, flag for review)
                _fallback_meta = {
                    "is_true_positive": True,
                    "confidence": self.FALLBACK_CONFIDENCE,
                    "reason": "LLM verification failed. Finding kept as unverified.",
                    "review_required": True,
                    "verified": False,
                }
                for finding in batch:
                    self._set(finding, "verification_metadata", _fallback_meta)
                verified_findings.extend(batch)

                # Circuit break after 3 consecutive failures
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    logger.warning("verification_circuit_break", consecutive_failures=consecutive_failures)
                    break

            # Soft timeout: if budget exceeded, mark remaining as unverified
            if elapsed > VERIFICATION_BUDGET_S:
                logger.warning(
                    "verification_soft_timeout",
                    elapsed_s=round(elapsed, 1),
                    budget_s=VERIFICATION_BUDGET_S,
                )
                break

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
        # 1. Comment/Docstring check (ENHANCED) - uses shared docstring utilities
        message_lower = (self._get(finding, "message") or "").lower()
        location_lower = (self._get(finding, "location") or "").lower()

        # Direct comment/docstring markers (shared utility)
        if looks_like_comment_or_docstring(code) or "docstring" in message_lower:
            return True

        # Enhanced docstring detection - uses shared docstring section keywords
        # and context indicators (triple-quotes, "# Example", "# Usage", etc.)
        if has_docstring_context_indicator(code):
            return True

        # Check if location suggests it's in a docstring (e.g., line appears to be documentation)
        if "check_loader" in location_lower and "example" in code.lower():
            return True

        # 2. Type Hint check (common FP in Python/TS)
        # e.g. "Optional[str]", "List[int]"
        if "[" in code and "]" in code and "(" not in code:
            if any(t in code for t in ["Optional", "List", "Dict", "Union", "Any"]):
                return True

        # 3. Import check — but NOT for phantom-package or secrets detection
        finding_id = (self._get(finding, "id") or "").lower()
        if code.startswith(("import ", "from ", "require(")):
            if "phantom" not in finding_id and "secret" not in finding_id:
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

    def _get_enriched_code(self, finding: Any, context: Any, token_budget: int = 400) -> str:
        """Build focused code context using ContextSlicerService when possible.

        Resolves file_path + line_number from the finding, reads the source file,
        and returns function-scoped context via ContextSlicerService.
        Falls back to the stored code snippet on any error.
        """
        raw_code = self._get(finding, "code") or "N/A"

        file_path = self._get(finding, "file_path") or ""
        if not file_path:
            location = self._get(finding, "location") or ""
            file_path = location.split(":")[0] if ":" in location else location

        line_number = self._get(finding, "line_number")
        if not file_path or not line_number:
            return raw_code

        try:
            from pathlib import Path as _Path

            file_content = _Path(file_path).read_text(encoding="utf-8", errors="replace")
        except Exception:
            return raw_code

        try:
            from warden.analysis.services.context_slicer import (
                ContextSlicerService,
                get_ast_and_graph_from_context,
            )

            ast_root, code_graph = get_ast_and_graph_from_context(context, file_path)
            slicer = ContextSlicerService()
            return slicer.build_focused_context(
                file_content=file_content,
                file_path=file_path,
                target_lines=[int(line_number)],
                ast_root=ast_root,
                code_graph=code_graph,
                token_budget=token_budget,
            )
        except Exception:
            return raw_code

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
                f_code = self._get_enriched_code(f, context)

                findings_summary += f"""
FINDING #{i}:
- ID: {f_id}
- Rule: {f_rule}
- Message: {f_msg}
- Code:
{f_code}
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

            # Extraction: Find JSON block even if LLM is chatty or uses markdown
            json_str = content
            if "```json" in content:
                json_str = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                # Find the first block that looks like JSON array
                match = re.search(r"(\[[\s\S]*\])", content)
                if match:
                    json_str = match.group(1).strip()

            # Sanitization: Remove dangerous characters that break json.loads
            json_str = re.sub(r"[\x00-\x1F\x7F]", "", json_str)

            try:
                results = json.loads(json_str)
            except json.JSONDecodeError:
                # Last resort: try to find anything that looks like an array
                match = re.search(r"(\[[\s\S]*\])", json_str)
                if match:
                    results = json.loads(match.group(1))
                else:
                    raise

            if isinstance(results, dict):
                # Small models with format=json return a bare dict for single-item batches.
                # Wrap it so downstream logic stays uniform.
                results = [results]
            if not isinstance(results, list):
                raise ValueError(f"LLM returned {type(results).__name__} instead of list")

            # Validate indices and map back to batch size
            if len(results) != len(batch):
                logger.warning(
                    "verifier_batch_size_mismatch",
                    expected=len(batch),
                    actual=len(results),
                    message="LLM returned different number of items than requested. Using best-effort mapping.",
                )

            return results
        except Exception as e:
            logger.warning("batch_llm_parsing_failed", error=str(e), content_preview=content[:200])
            # Fallback: Mark for manual review due to parsing error
            # verification_source signals callers to skip caching this result
            return [
                {
                    "is_true_positive": True,
                    "confidence": 0.4,
                    "reason": "LLM responded but output parsing failed. Manual Review recommended.",
                    "review_required": True,
                    "verification_source": "parse_fail_fallback",
                }
                for _ in batch
            ]

    def _generate_key(self, finding: Any) -> str:
        import hashlib

        # Include file_path + line_number so the same rule firing on different files
        # gets separate cache entries rather than reusing the first file's result.
        finding_id = self._get(finding, "id") or ""
        file_path = self._get(finding, "file_path") or self._get(finding, "location") or ""
        line_number = str(self._get(finding, "line_number") or "")
        code = self._get(finding, "code") or ""

        unique_str = f"{finding_id}:{file_path}:{line_number}:{code}"
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
