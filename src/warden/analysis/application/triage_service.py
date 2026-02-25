"""
Triage Service for Adaptive Hybrid Triage.
Uses Local LLM to assess file risk and complexity.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING

import psutil
import structlog

from warden.analysis.domain.triage_heuristics import is_heuristic_safe
from warden.analysis.domain.triage_models import RiskScore, TriageDecision, TriageLane
from warden.llm.providers.base import ILlmClient
from warden.llm.types import LlmRequest
from warden.validation.domain.frame import CodeFile

if TYPE_CHECKING:
    from warden.analysis.application.triage_cache import TriageCacheManager

logger = structlog.get_logger(__name__)

# Provider-aware batch sizes.
# Larger batches reduce the number of LLM round-trips at the cost of more
# context tokens per request.
_BATCH_SIZES: dict[str, int] = {
    "ollama": 5,  # Small local models (e.g. Qwen 3b, 2K context)
    "groq": 15,  # Fast cloud API, 32K+ context
    "openai": 15,  # Cloud API, 128K context
    "azure_openai": 15,
    "anthropic": 15,
    "openrouter": 15,
    "deepseek": 15,
    "qwencode": 15,
    "gemini": 15,
    # CLI-tool providers: safety net if bypass fails to activate
    "claude_code": 25,
    "codex": 25,
}
_DEFAULT_BATCH_SIZE = 5


class TriageService:
    """
    Service for determining the analysis depth (Lane) for a code file.
    Uses Local LLM (The Sieve) to assign risk scores.
    """

    SYSTEM_PROMPT = """
    You are a Senior Security Architect acting as a Triage Gatekeeper.
    Your goal is to assess the SECURITY RISK and COMPLEXITY of the provided code.

    Analyze the code for:
    1. Security logic (Auth, Crypto, Input validation, SQL, Permissions)
    2. Business logic complexity (State management, External APIs, Data processing)
    3. Structural role (DTO, Config, UI, Test, Utility)

    Output strictly VALID JSON:
    {
        "score": <float 0.0-10.0>,
        "confidence": <float 0.0-1.0>,
        "category": "<string>",
        "reasoning": "<string>"
    }

    Scoring Guide:
    0-3: Safe (DTO, Config, UI).
    4-7: Suspicious (Logic, Controllers).
    8-10: Critical (Auth, Crypto, SQL).
    """

    BATCH_SYSTEM_PROMPT = """You are a Senior Security Architect acting as a Triage Gatekeeper.
You will receive MULTIPLE files. For EACH file, assess its security risk and complexity.

Output a single JSON object where EVERY key is a file path from the input.

EXAMPLE OUTPUT (for 2 files):
=== BEGIN EXAMPLE ===
{
    "src/auth/login.py": {"score": 8.5, "confidence": 0.95, "category": "Auth", "reasoning": "Handles password verification and session creation."},
    "src/models/dto.py": {"score": 1.0, "confidence": 1.0, "category": "DTO", "reasoning": "Simple data container with no logic."}
}
=== END EXAMPLE ===

Scoring Guide:
0-3: Safe (DTO, Config, UI, Test).
4-7: Suspicious (Logic, Controllers, Services).
8-10: Critical (Auth, Crypto, SQL, Permissions).

Rules:
- Output ONLY the JSON object. No markdown. No explanation outside JSON.
- Every file path from the input MUST appear as a key in the output.
- Reasoning MUST be 1 short sentence.
"""

    def __init__(
        self,
        llm_client: ILlmClient,
        cache: TriageCacheManager | None = None,
    ):
        self.llm = llm_client
        self._cache = cache

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

        # Provider-aware batch size
        self._requested_batch_size = self._determine_batch_size(llm_client)

    @staticmethod
    def _determine_batch_size(llm_client: ILlmClient) -> int:
        """Choose batch size based on the provider that handles triage requests.

        Triage always sends ``use_fast_tier=True``, so the batch size must
        match the **fast-tier** provider's context window — not the smart
        tier.  For OrchestratedLlmClient we inspect ``fast_clients`` first;
        if there are none (single-tier mode) we fall back to the smart
        client.
        """
        # 1. OrchestratedLlmClient with fast tier → use first fast client
        fast_clients = getattr(llm_client, "fast_clients", None)
        if fast_clients:
            first_fast = fast_clients[0]
            fast_provider = str(getattr(first_fast, "provider", "")).lower()
            if fast_provider in _BATCH_SIZES:
                return _BATCH_SIZES[fast_provider]

        # 2. Direct provider attribute (non-orchestrated or single-tier)
        provider_str = str(getattr(llm_client, "provider", "")).lower()
        if provider_str in _BATCH_SIZES:
            return _BATCH_SIZES[provider_str]

        # 3. Orchestrated without fast tier → smart client determines size
        for attr in ("_smart_client", "smart_client"):
            inner = getattr(llm_client, attr, None)
            if inner:
                inner_provider = str(getattr(inner, "provider", "")).lower()
                if inner_provider in _BATCH_SIZES:
                    return _BATCH_SIZES[inner_provider]

        return _DEFAULT_BATCH_SIZE

    async def batch_assess_risk_async(self, code_files: list[CodeFile]) -> dict[str, TriageDecision]:
        """
        Assess risk for multiple files in batches.
        """
        start_time = time.time()
        decisions: dict[str, TriageDecision] = {}
        files_to_process: list[CodeFile] = []

        # 1. Fast Path: Heuristic-safe files skip LLM entirely
        for cf in code_files:
            if is_heuristic_safe(cf):
                decisions[cf.path] = self._create_decision(
                    cf, TriageLane.FAST, 0, "Heuristic: Safe file type/content", start_time
                )
                continue

            # 2. Cache hit check (hash-based)
            if self._cache:
                cached = self._cache.get(cf.path, cf.content)
                if cached is not None:
                    decisions[cf.path] = cached
                    continue

            files_to_process.append(cf)

        if not files_to_process:
            self._flush_cache()
            return decisions

        # 3. Batch Processing for remaining files
        requested_batch_size = self._requested_batch_size

        i = 0
        while i < len(files_to_process):
            # Dynamic resource-check
            batch_size = self._get_safe_batch_size(requested_batch_size)
            chunk = files_to_process[i : i + batch_size]

            try:
                batch_scores = await self._get_llm_batch_score_async(chunk)

                # Check for flat fallback (common on small models)
                flat_fallback = batch_scores.get("_flat_fallback_")

                for cf in chunk:
                    # 1. Try exact path match
                    risk = batch_scores.get(cf.path)

                    # 2. Try just the filename match (sometimes LLM trims paths)
                    if not risk:
                        filename = Path(cf.path).name
                        risk = next((v for k, v in batch_scores.items() if k.endswith(filename)), None)

                    # 3. Use flat fallback if available
                    if not risk and flat_fallback:
                        risk = flat_fallback

                    if not risk:
                        # Fallback to middle lane
                        logger.warning("triage_batch_missing_file", file=cf.path)
                        decision = self._create_decision(
                            cf, TriageLane.MIDDLE, 5, "Batch fallback: Missing from LLM response", start_time
                        )
                    else:
                        lane = self._determine_lane(risk)
                        decision = TriageDecision(
                            file_path=str(cf.path),
                            lane=lane,
                            risk_score=risk,
                            processing_time_ms=(time.time() - start_time) * 1000,
                        )

                    decisions[cf.path] = decision

                    # Store in cache
                    if self._cache:
                        self._cache.put(cf.path, cf.content, decision)

            except Exception as e:
                logger.error("triage_batch_failed", error=str(e), chunk_size=len(chunk))
                # Fallback for entire chunk
                for cf in chunk:
                    decisions[cf.path] = self._create_decision(
                        cf, TriageLane.MIDDLE, 5, f"Batch error: {e!s}", start_time
                    )

            i += len(chunk)

        self._flush_cache()
        return decisions

    def _flush_cache(self) -> None:
        if self._cache:
            self._cache.flush()

    async def _get_llm_batch_score_async(self, code_files: list[CodeFile]) -> dict[str, RiskScore]:
        """Calls Local LLM to get risk scores for multiple files."""
        from warden.shared.utils.llm_context import BUDGET_TRIAGE, prepare_code_for_llm, resolve_token_budget

        budget = resolve_token_budget(BUDGET_TRIAGE, is_fast_tier=True)

        # Prepare batch prompt
        files_context = []
        for cf in code_files:
            # Shortened snippet for triage to save context tokens
            content_snippet = prepare_code_for_llm(cf.content, token_budget=budget).replace("```", "'''")
            files_context.append(f"=== FILE: {cf.path} ===\n{content_snippet}")

        context_str = "\n\n".join(files_context)

        prompt = f"""Analyze the {len(code_files)} file(s) below.
Output a JSON object where EVERY key is one of the file paths listed.

FILES:
{context_str}
"""
        request = LlmRequest(
            system_prompt=self.BATCH_SYSTEM_PROMPT,
            user_message=prompt,
            use_fast_tier=True,
            temperature=0.01,
            max_tokens=min(2000, 300 * len(code_files)),
        )

        response = await self.llm.send_async(request)

        if not response.success:
            raise RuntimeError(f"LLM batch failed: {response.error_message}")

        return self._parse_batch_response(response.content)

    def _parse_batch_response(self, content: str) -> dict[str, RiskScore]:
        """Parses batch JSON response."""
        try:
            json_str = self._extract_json(content)
            data = json.loads(json_str)

            # Case 1: Model returned a flat object instead of a map (common on very small models)
            # If "score" is a top-level key, it's a flat object.
            if "score" in data and ("reasoning" in data or "category" in data):
                logger.warning("triage_batch_flat_object_detected", content=content[:100])
                return {"_flat_fallback_": RiskScore(**data)}

            results = {}
            for path, score_data in data.items():
                try:
                    # Skip non-dict items (like the flattened fields if the model mixed them)
                    if not isinstance(score_data, dict):
                        continue

                    # Normalize keys if needed (LLM might lowercase them)
                    if "risk_score" in score_data:
                        score_data = score_data["risk_score"]
                    results[path] = RiskScore(**score_data)
                except Exception as e:
                    logger.warning("triage_batch_item_parse_failed", path=path, error=str(e))

            return results
        except Exception as e:
            logger.error("triage_batch_json_parse_failed", error=str(e), content=content[:200])
            raise e

    def _is_obviously_safe(self, code_file: CodeFile) -> bool:
        """Legacy heuristic — delegates to shared module."""
        return is_heuristic_safe(code_file)

    async def _get_llm_score_async(self, code_file: CodeFile) -> RiskScore:
        """Calls Local LLM to get risk score."""
        from warden.shared.utils.llm_context import BUDGET_TRIAGE, prepare_code_for_llm, resolve_token_budget

        budget = resolve_token_budget(BUDGET_TRIAGE, is_fast_tier=True)
        truncated = prepare_code_for_llm(code_file.content, token_budget=budget)
        prompt = f"File Path: {code_file.path}\n\nCode:\n```{code_file.language}\n{truncated}```"

        request = LlmRequest(
            system_prompt=self.SYSTEM_PROMPT, user_message=prompt, use_fast_tier=True, temperature=0.1, max_tokens=250
        )

        response = await self.llm.send_async(request)

        if not response.success:
            raise RuntimeError(f"LLM failed: {response.error_message}")

        return self._parse_response(response.content)

    def _parse_response(self, content: str) -> RiskScore:
        """Parses LLM JSON response with Chaos Hardening."""
        try:
            # 1. Extraction: Find JSON block even if LLM is chatty
            json_str = self._extract_json(content)

            # 2. Sanitization: Remove dangerous characters that break json.loads
            # (Sometimes Qwen adds control characters)
            json_str = re.sub(r"[\x00-\x1F\x7F]", "", json_str)

            data = json.loads(json_str)

            # 3. Validation: Use Pydantic to normalize (30 -> 3.0) and validate
            return RiskScore(**data)

        except Exception as e:
            logger.warning("triage_parse_failed", content=content[:200], error=str(e))
            # Fallback score (Safe enough for middle lane, high enough for attention)
            return RiskScore(score=5.0, confidence=0.0, reasoning=f"Parsing Error: {e!s}", category="chaos_fallback")

    def _extract_json(self, text: str) -> str:
        """Extract JSON object from LLM response, ignoring surrounding chatter."""
        text = text.strip()

        # 1. Try markdown code block first
        if "```json" in text:
            start = text.find("```json") + 7
            snippet = text[start:]
            end = snippet.find("```")
            if end != -1:
                return snippet[:end].strip()

        # 2. Find the first top-level JSON object via brace balancing
        depth = 0
        obj_start = -1
        for i, ch in enumerate(text):
            if ch == "{":
                if depth == 0:
                    obj_start = i
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0 and obj_start != -1:
                    return text[obj_start : i + 1]

        # 3. Last resort: greedy match from first { to last }
        first_brace = text.find("{")
        last_brace = text.rfind("}")
        if first_brace != -1 and last_brace > first_brace:
            return text[first_brace : last_brace + 1]

        return text

    def _get_safe_batch_size(self, max_allowed: int) -> int:
        """Adaptive batch size based on RAM/CPU."""
        if not getattr(self, "is_local", False):
            return max_allowed
        try:
            mem = psutil.virtual_memory()
            available_gb = mem.available / (1024**3)
            mem_limit = max(1, int(available_gb // 2.0))  # Triage is simpler, 2GB per item

            cpu_load = psutil.cpu_percent(interval=None)
            cpu_limit = 1 if cpu_load > 80 else max_allowed

            return min(max_allowed, mem_limit, cpu_limit, (os.cpu_count() or 2) // 2)
        except (AttributeError, psutil.Error, OSError):
            # psutil unavailable or error - default to safe value
            return 1

    def _determine_lane(self, risk: RiskScore) -> TriageLane:
        """Routing logic based on risk score."""
        if risk.score <= 3.5:
            return TriageLane.FAST
        elif risk.score <= 7.5:
            return TriageLane.MIDDLE
        else:
            return TriageLane.DEEP

    def _create_decision(
        self, code_file: CodeFile, lane: TriageLane, score: int, reason: str, start_time: float
    ) -> TriageDecision:
        return TriageDecision(
            file_path=str(code_file.path),
            lane=lane,
            risk_score=RiskScore(score=score, confidence=1.0, reasoning=reason, category="heuristic"),
            processing_time_ms=(time.time() - start_time) * 1000,
        )
