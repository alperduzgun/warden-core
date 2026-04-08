import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any

import psutil

from warden.analysis.services.prompt_loader import PromptLoader
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

_MAX_CODE_FILE_BYTES: int = 256 * 1024  # 256 KB — prevents OOM on large/generated files

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
    # Minimum LLM-returned confidence to accept a verified finding as true positive.
    # Findings with confidence below this threshold are treated as false positives
    # and dropped. Configurable via constructor kwarg ``confidence_threshold``.
    DEFAULT_CONFIDENCE_THRESHOLD = 0.55

    def _get(self, obj: Any, key: str, default: Any = None) -> Any:
        """Helper to get values from Finding objects or dicts (Deprecated: Use finding_utils)."""
        return get_finding_attribute(obj, key, default)

    def _set(self, obj: Any, key: str, value: Any) -> None:
        """Helper to set values on Finding objects or dicts (Deprecated: Use finding_utils)."""
        from warden.shared.utils.finding_utils import set_finding_attribute

        set_finding_attribute(obj, key, value)

    def __init__(
        self,
        llm_client: ILlmClient,
        memory_manager: MemoryManager | None = None,
        enabled: bool = True,
        confidence_threshold: float | None = None,
        project_root: Path | None = None,
    ):
        self.llm = llm_client
        self.memory_manager = memory_manager
        self.enabled = enabled
        self.confidence_threshold = (
            confidence_threshold
            if confidence_threshold is not None
            else self.DEFAULT_CONFIDENCE_THRESHOLD
        )

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

        # Load system prompt via PromptLoader — supports project-level override at
        # .warden/prompts/verifier_system.md, falls back to the package default.
        self._prompt_loader = PromptLoader(project_root=project_root)
        self.system_prompt = self._prompt_loader.load("verifier_system")

    async def verify_findings_async(self, findings: list[dict[str, Any]], context: Any = None) -> list[dict[str, Any]]:
        """
        Filters out false positives from the findings list using:
        Heuristic Filter -> Cache -> Parallel Category LLM Verification.

        Findings that reach the LLM stage are first grouped by category
        (secrets / taint / structural / other) and all categories are
        verified concurrently via asyncio.gather for lower end-to-end latency.
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

            # Exempt high-precision findings from LLM verification when they have
            # full confidence.  If a finding from these sources carries a reduced
            # pattern_confidence (set by context-aware checks), route it to LLM
            # for a second opinion rather than accepting it unconditionally.
            det_source = (
                self._get(finding, "detection_source")
                or self._get(finding, "detectionSource")
            )
            _pc1 = self._get(finding, "pattern_confidence")
            _pc2 = self._get(finding, "patternConfidence")
            pattern_conf = _pc1 if _pc1 is not None else _pc2
            has_reduced_confidence = (
                pattern_conf is not None and float(pattern_conf) < 0.75
            )
            if det_source in _HIGH_PRECISION_SOURCES and not has_reduced_confidence:
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
                    # Propagate confidence from cached verification result
                    cached_confidence = self._get(cached_result, "confidence")
                    if cached_confidence is not None:
                        self._set(finding, "verification_confidence", float(cached_confidence))
                    verified_findings.append(finding)
                continue

            remaining_after_cache.append(finding)

        if not remaining_after_cache:
            return verified_findings

        # STEP 3: Parallel Category LLM Verification
        # Group by category and verify each category concurrently.
        categories = self._categorize_findings(remaining_after_cache)
        logger.info(
            "verification_parallelized",
            categories=list(categories.keys()),
            total_findings=len(remaining_after_cache),
        )

        category_results = await asyncio.gather(
            *[self._verify_category(cat, items, context) for cat, items in categories.items()],
            return_exceptions=True,
        )

        for cat_outcome in category_results:
            if isinstance(cat_outcome, Exception):
                # A whole category failed — log and skip (findings stay unverified).
                logger.error("category_verification_failed", error=str(cat_outcome))
                continue
            verified_findings.extend(cat_outcome)

        logger.info(
            "verification_summary",
            initial=initial_count,
            final=len(verified_findings),
            reduction=f"{((initial_count - len(verified_findings)) / initial_count) * 100:.1f}%"
            if initial_count > 0
            else "0%",
        )

        return verified_findings

    # ------------------------------------------------------------------
    # Category helpers (Issue #621)
    # ------------------------------------------------------------------

    _SECRETS_KEYWORDS = frozenset({"secret", "password", "token", "key", "credential"})
    _TAINT_KEYWORDS = frozenset({"sql", "injection", "xss", "command"})
    _STRUCTURAL_KEYWORDS = frozenset({"orphan", "unused", "unreferenced"})

    def _categorize_findings(self, findings: list) -> dict[str, list]:
        """Group findings by verification category.

        Categories:
          secrets    — rule_id contains: secret / password / token / key / credential
          taint      — rule_id contains: sql / injection / xss / command
          structural — rule_id contains: orphan / unused / unreferenced
          other      — everything else

        Each category is verified concurrently so that slow LLM calls for one
        category do not block another.
        """
        result: dict[str, list] = {"secrets": [], "taint": [], "structural": [], "other": []}

        for finding in findings:
            rule_id = (self._get(finding, "rule_id") or self._get(finding, "id") or "").lower()

            if any(kw in rule_id for kw in self._SECRETS_KEYWORDS):
                result["secrets"].append(finding)
            elif any(kw in rule_id for kw in self._TAINT_KEYWORDS):
                result["taint"].append(finding)
            elif any(kw in rule_id for kw in self._STRUCTURAL_KEYWORDS):
                result["structural"].append(finding)
            else:
                result["other"].append(finding)

        # Drop empty categories so asyncio.gather has fewer tasks.
        return {cat: items for cat, items in result.items() if items}

    async def _verify_category(self, category: str, findings: list, context: Any) -> list:
        """Verify all findings in a single category using token-aware batching.

        Mirrors the original sequential batch loop (with circuit break and soft
        timeout) but scoped to one category so categories run in parallel.
        """
        import time as _time

        MAX_CONSECUTIVE_FAILURES = 3
        MAX_BATCH_TOKENS = 4000
        MAX_BATCH_SIZE = self._get_safe_batch_size(10)
        VERIFICATION_BUDGET_S = 90.0

        def _make_fallback_meta(reason: str) -> dict:
            return {
                "is_true_positive": True,
                "confidence": self.FALLBACK_CONFIDENCE,
                "reason": reason,
                "fallback": True,
                "review_required": True,
                "verified": False,
            }

        # Build token-aware batches for this category.
        batches: list[list] = []
        cur_batch: list = []
        cur_tokens = 0
        for finding in findings:
            msg = getattr(finding, "message", "") or (
                finding.get("message", "") if isinstance(finding, dict) else ""
            ) or ""
            code = getattr(finding, "code", "") or (
                finding.get("code", "") if isinstance(finding, dict) else ""
            ) or ""
            est = len(msg.split()) + len(code.split())
            if cur_tokens + est > MAX_BATCH_TOKENS or len(cur_batch) >= MAX_BATCH_SIZE:
                if cur_batch:
                    batches.append(cur_batch)
                cur_batch = [finding]
                cur_tokens = est
            else:
                cur_batch.append(finding)
                cur_tokens += est
        if cur_batch:
            batches.append(cur_batch)

        logger.info("batch_verification_starting", category=category, count=len(findings))

        verified: list = []
        _start = _time.monotonic()
        consecutive_failures = 0
        processed_count = 0
        circuit_broken = False
        timed_out = False

        for batch in batches:
            elapsed = _time.monotonic() - _start
            if elapsed > VERIFICATION_BUDGET_S:
                logger.warning(
                    "verification_soft_timeout",
                    category=category,
                    elapsed_s=round(elapsed, 1),
                    budget_s=VERIFICATION_BUDGET_S,
                )
                timed_out = True
                break

            try:
                results = await self._verify_batch_with_llm_async(batch, context)
                consecutive_failures = 0
                for idx, result in enumerate(results):
                    finding = batch[idx]
                    cache_key = self._generate_key(finding)
                    if self._get(result, "verification_source") != "parse_fail_fallback":
                        self._save_cache(cache_key, result)
                    is_tp = self._get(result, "is_true_positive", True)
                    if is_tp:
                        result_confidence = self._get(result, "confidence")
                        # Drop findings that are true-positive but below confidence threshold.
                        # This filters low-signal pattern matches that LLM is uncertain about.
                        if result_confidence is not None and float(result_confidence) < self.confidence_threshold:
                            logger.info(
                                "finding_dropped_low_confidence",
                                finding_id=self._get(finding, "id"),
                                confidence=float(result_confidence),
                                threshold=self.confidence_threshold,
                            )
                            continue
                        self._set(finding, "verification_metadata", result)
                        if result_confidence is not None:
                            self._set(finding, "verification_confidence", float(result_confidence))
                        verified.append(finding)
            except Exception as e:
                logger.error("batch_verification_failed", category=category, error=str(e))
                consecutive_failures += 1
                fb = _make_fallback_meta("LLM verification failed. Finding kept as unverified.")
                for finding in batch:
                    self._set(finding, "verification_metadata", fb)
                verified.extend(batch)

                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    logger.warning(
                        "verification_circuit_break",
                        category=category,
                        consecutive_failures=consecutive_failures,
                    )
                    circuit_broken = True
                    processed_count += len(batch)
                    break

            processed_count += len(batch)

        if circuit_broken or timed_out:
            unprocessed = findings[processed_count:]
            if unprocessed:
                reason = (
                    "Verification skipped: circuit break after consecutive LLM failures."
                    if circuit_broken
                    else "Verification skipped: soft timeout exceeded."
                )
                fb = _make_fallback_meta(reason)
                for finding in unprocessed:
                    self._set(finding, "verification_metadata", fb)
                verified.extend(unprocessed)

        return verified

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

            file_content = _Path(file_path).read_bytes()[:_MAX_CODE_FILE_BYTES].decode("utf-8", errors="replace")
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

        prompt = self._prompt_loader.load(
            "verifier_batch",
            batch_size=str(len(batch)),
            context_prompt=context_prompt,
            findings_summary=findings_summary,
        )
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
        """Generate a cross-file cache key using (rule_id, code_snippet_hash).

        The key deliberately excludes file_path so that the same vulnerability
        pattern in multiple files shares a single cache entry.  If no code
        snippet is available the finding message is used as the content anchor.

        Old entries produced by the previous (file-path-inclusive) scheme simply
        won't match the new keys — they produce a graceful cache miss and are
        re-verified normally.
        """
        import hashlib

        rule_id = self._get(finding, "rule_id") or self._get(finding, "id") or ""
        code_snippet = (self._get(finding, "code") or "").strip()

        if code_snippet:
            content_hash = hashlib.md5(code_snippet.encode()).hexdigest()[:12]
        else:
            message = (self._get(finding, "message") or "").strip()
            content_hash = hashlib.md5(message.encode()).hexdigest()[:12]

        return f"{rule_id}:{content_hash}"

    def _check_cache(self, key: str) -> dict | None:
        try:
            if self.memory_manager:
                result = self.memory_manager.get_llm_cache(f"verify:{key}")
                if result is not None:
                    logger.debug("verification_cache_hit", key=key)
                return result
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
