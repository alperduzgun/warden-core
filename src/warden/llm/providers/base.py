"""
Base LLM Client Interface

Based on C# ILlmClient.cs:
/Users/alper/vibe-code-analyzer/src/Warden.LLM/ILlmClient.cs

All provider implementations must inherit from this interface
"""

import asyncio
import json
from abc import ABC, abstractmethod
from pathlib import Path

from warden.shared.infrastructure.exceptions import ExternalServiceError
from warden.shared.infrastructure.logging import get_logger

from ..types import LlmProvider, LlmRequest, LlmResponse

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Shared provider-error detection (rate limits, quota exhaustion, etc.)
# ---------------------------------------------------------------------------

_RATE_LIMIT_PATTERNS = [
    "usage limit",
    "rate limit",
    "try again in",
    "too many requests",
    "quota exceeded",
    "request limit reached",
    "throttled",
]


def detect_provider_error(content: str) -> str | None:
    """Detect rate-limit or quota-exhaustion messages in provider output.

    Returns a truncated error snippet (max 200 chars) if a pattern matches,
    otherwise ``None``.
    """
    lower = content.lower()
    for pattern in _RATE_LIMIT_PATTERNS:
        if pattern in lower:
            return content.strip()[:200]
    return None


class ILlmClient(ABC):
    """
    Interface for LLM providers

    Matches C# ILlmClient interface
    All providers (Anthropic, DeepSeek, QwenCode, etc.) must implement this
    """

    _project_root: Path | None = None

    @property
    @abstractmethod
    def provider(self) -> LlmProvider:
        """
        The provider type

        Returns:
            LlmProvider enum value
        """
        pass

    @abstractmethod
    async def send_async(self, request: LlmRequest) -> LlmResponse:
        """
        Send a request to the LLM provider

        Args:
            request: The LLM request parameters

        Returns:
            LLM response with content or error

        Raises:
            Should NOT raise exceptions - return LlmResponse with success=False instead
        """
        pass

    @abstractmethod
    async def is_available_async(self) -> bool:
        """
        Check if the provider is available/configured

        Returns:
            True if the provider is ready to use, False otherwise

        Note:
            Should NOT raise exceptions - return False on any error
        """
        pass

    async def send_with_tools_async(self, request: LlmRequest) -> LlmResponse:
        """Send request with agentic tool loop support.

        Calls send_async(), then if response contains tool_use and
        provider is not Claude Code, enters the agentic loop.
        Re-calls use send_async() directly (no recursion).
        """
        response = await self.send_async(request)
        if not response.success or not response.content:
            return response

        from warden.llm.agentic_runner import (
            detect_tool_use,
            is_claude_code_provider,
            run_agentic_loop_async,
        )

        if is_claude_code_provider(self):
            return response
        if detect_tool_use(response.content) is None:
            return response

        async def llm_call_fn(augmented_prompt: str, sys_prompt: str) -> LlmResponse:
            new_request = LlmRequest(
                user_message=augmented_prompt,
                system_prompt=sys_prompt,
                model=request.model,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                use_fast_tier=request.use_fast_tier,
            )
            return await self.send_async(new_request)

        return await run_agentic_loop_async(
            initial_response=response,
            llm_call_fn=llm_call_fn,
            original_prompt=request.user_message,
            system_prompt=request.system_prompt,
            project_root=self._project_root,
            caller_name="llm_client",
        )

    async def complete_async(
        self,
        prompt: str,
        system_prompt: str = "You are a helpful coding assistant.",
        model: str | None = None,
        use_fast_tier: bool = False,
        max_tokens: int = 4000,
    ) -> LlmResponse:
        """
        Simple completion method for non-streaming requests.

        Args:
            prompt: User prompt
            system_prompt: System prompt (optional)
            model: Model override (optional)
            use_fast_tier: If True, request fast (local) tier
            max_tokens: Maximum tokens to generate. Callers that know their
                response budget (e.g. LLMPhaseConfig) should pass this
                explicitly so slow local providers (Ollama on CPU) can finish
                within the asyncio.wait_for timeout.

        Returns:
            LlmResponse with content and token usage

        Raises:
            Exception: If request fails
        """
        request = LlmRequest(
            user_message=prompt,
            system_prompt=system_prompt,
            model=model,
            temperature=0.0,
            max_tokens=max_tokens,
            timeout_seconds=300.0,
            use_fast_tier=use_fast_tier,
        )

        try:
            response = await asyncio.wait_for(
                self.send_with_tools_async(request),
                timeout=request.timeout_seconds,
            )
        except asyncio.TimeoutError:
            return LlmResponse.error(
                f"LLM call timed out after {request.timeout_seconds}s",
                provider=self.provider,
            )

        if not response.success:
            raise ExternalServiceError(f"LLM request failed: {response.error_message}")

        return response

    # ── Chunked security analysis ──────────────────────────────────────────────
    _SECURITY_PROMPT = """Analyze this {language} code for security vulnerabilities. Focus on exploitable flaws only.

CHECK THESE FIRST (report each one found):
1. == comparing password/hash/token/secret byte values (NOT role names or status strings) — timing attack, use hmac.compare_digest
2. JWT decode accepting "none" algorithm (auth bypass)
3. JWT expiry >7 days (token theft)
4. Role/permission from JWT payload without server-side check (privilege escalation)
5. MD5/SHA1 with static/hardcoded salt (weak crypto)
6. format()/format_map() with user input (attribute leak via __class__)
7. random module generating security tokens, session IDs, reset codes, or unpredictable paths (NOT for shuffle/sample/simulation)
8. HTML sanitizer using string replace() blocklist (bypassable)
9. Validation regex using .* or trivially bypassable patterns

10. Open redirect: redirect()/res.redirect()/HttpResponseRedirect() with user-controlled URL without allowlist
11. Logging sensitive data: password/token/secret/key variable in log/print/console.log
12. Race condition / TOCTOU: check-then-act without lock (e.g., if exists(f): open(f))
13. Insecure deserialization: pickle.load/yaml.load/ObjectInputStream.readObject/node-serialize on untrusted data
14. Mass assignment / prototype pollution: Object.assign(obj, req.body) or Model(**request.data) without field allowlist
15. Unvalidated file upload: accepting files without type/size/extension check

ALSO CHECK: SQL Injection, XSS, Hardcoded Secrets, SSRF, CSRF, XXE, Command Injection, Path Traversal, IDOR.
IDOR: endpoint uses user-controlled ID without ownership check (parameterized query alone is NOT enough).
ALSO CHECK these code quality security issues:
- Unbounded in-memory cache/dict without eviction (memory exhaustion DoS)
- Secrets/credentials/private keys stored in process memory longer than needed
- Broad except Exception swallowing programming errors as API errors
- Binding to 0.0.0.0 without access controls
- Missing input validation on user-controlled IDs passed into URL paths
For each finding include source (where tainted data enters) and sink (where it is consumed unsafely) if applicable.

IMPORTANT: Output ONLY valid JSON. No markdown.
{{"findings":[{{"severity":"critical|high|medium","message":"Short description","line_number":1,"detail":"Exploit explanation","source":"entry point","sink":"unsafe consumption"}}]}}
If no issues: {{"findings":[]}}

{chunk_header}```{language}
{code}
```"""

    _CHUNK_TOKEN_LIMIT = 4000
    _LOCAL_LLM_PROVIDERS = frozenset({LlmProvider.QWEN_CLI, LlmProvider.OLLAMA, LlmProvider.CLAUDE_CODE, LlmProvider.CODEX})

    async def analyze_security_async(self, code_content: str, language: str, use_fast_tier: bool = False) -> dict:
        """Analyze code for security vulnerabilities. Chunks large files automatically."""
        from warden.shared.utils.llm_context import BUDGET_SECURITY, prepare_code_for_llm, resolve_token_budget
        from warden.shared.utils.token_utils import estimate_tokens

        is_local = self.provider in self._LOCAL_LLM_PROVIDERS
        budget_tokens = self._CHUNK_TOKEN_LIMIT if is_local else resolve_token_budget(BUDGET_SECURITY).tokens
        code_tokens = estimate_tokens(code_content)

        # Small file: single call, no chunking
        if code_tokens <= budget_tokens:
            return await self._analyze_security_single(code_content, language, use_fast_tier, "")

        # API provider: truncate (cost matters)
        if not is_local:
            truncated = prepare_code_for_llm(code_content, token_budget=resolve_token_budget(BUDGET_SECURITY))
            return await self._analyze_security_single(truncated, language, use_fast_tier, "")

        # Local LLM + large file: chunk
        chunks = self._split_code_chunks(code_content, budget_tokens)
        logger.info("analyze_security_chunked", chunks=len(chunks), total_tokens=code_tokens)

        all_findings: list[dict] = []
        for i, chunk in enumerate(chunks):
            header = (
                f"This is part {i + 1} of {len(chunks)} of the same file "
                f"(lines {chunk['start']}-{chunk['end']}). "
            )
            if i > 0:
                header += "Report only NEW findings in THIS section. "
            header += "\n\n"

            result = await self._analyze_security_single(chunk["code"], language, use_fast_tier, header)
            for f in result.get("findings", []):
                if isinstance(f.get("line_number"), int):
                    raw = f["line_number"]
                    # If LLM returned an absolute line (within chunk range), keep it.
                    # If it returned a relative line (< chunk start), apply offset.
                    if not (chunk["start"] <= raw <= chunk["end"]):
                        f["line_number"] = raw + chunk["start"] - 1
                all_findings.append(f)

        deduped = self._dedup_findings(all_findings)
        logger.info("analyze_security_chunked_done", raw=len(all_findings), deduped=len(deduped))
        return {"findings": deduped}

    def _split_code_chunks(self, code: str, budget: int) -> list[dict]:
        """Split code into chunks with 10-line overlap for context continuity."""
        from warden.shared.utils.token_utils import estimate_tokens

        lines = code.splitlines(keepends=True)
        overlap = 20
        chunks: list[dict] = []
        pos = 0
        while pos < len(lines):
            tok = 0
            end = pos
            while end < len(lines):
                lt = estimate_tokens(lines[end])
                if tok + lt > budget and end > pos:
                    break
                tok += lt
                end += 1
            numbered = [f"{pos + i + 1}: {line}" for i, line in enumerate(lines[pos:end])]
            chunks.append({"code": "".join(numbered), "start": pos + 1, "end": end})
            if end >= len(lines):
                break
            pos = max(pos + 1, end - overlap)
        return chunks

    @staticmethod
    def _dedup_findings(findings: list[dict]) -> list[dict]:
        """Remove near-duplicate findings (same line ±3, similar message)."""
        seen: set[tuple[int, str]] = set()
        out: list[dict] = []
        for f in findings:
            key = (f.get("line_number", 0) // 3, f.get("message", "").lower()[:40])
            if key not in seen:
                seen.add(key)
                out.append(f)
        return out

    async def _analyze_security_single(self, code: str, language: str, use_fast_tier: bool, chunk_header: str) -> dict:
        """Single LLM call for security analysis."""
        from warden.shared.utils.json_parser import parse_json_from_llm
        from warden.llm.prompts.tool_instructions import get_tool_enhanced_prompt

        prompt = self._SECURITY_PROMPT.format(
            language=language, code=code, chunk_header=chunk_header,
        )
        system_prompt = get_tool_enhanced_prompt("You are a strict security auditor. Output valid JSON only.")

        try:
            response = await self.complete_async(prompt, system_prompt=system_prompt, use_fast_tier=use_fast_tier)
            if not response.success:
                logger.warning("analyze_security_llm_failed", reason="response.success=False")
                return {"findings": []}
            logger.debug("analyze_security_raw_response", content_length=len(response.content) if response.content else 0, content_preview=str(response.content)[:500] if response.content else "None")
            parsed = parse_json_from_llm(response.content)
            if not parsed:
                logger.warning("analyze_security_parse_failed", content_preview=str(response.content)[:500] if response.content else "None")
                return {"findings": []}
            logger.debug("analyze_security_parsed", findings_count=len(parsed.get("findings", [])))
            self._enrich_findings_from_llm(parsed)
            return parsed
        except (json.JSONDecodeError, ValueError, KeyError) as exc:
            logger.warning("analyze_security_exception", error=str(exc), content_preview=str(response.content)[:500] if 'response' in locals() else "no_response")
            return {"findings": []}

    @staticmethod
    def _enrich_findings_from_llm(parsed: dict) -> None:
        """Attach machine_context to parsed findings when source/sink/data_flow present."""
        from warden.shared.utils.prompt_sanitizer import PromptSanitizer

        for item in parsed.get("findings", []):
            has_structured = item.get("source") or item.get("sink") or item.get("data_flow")
            if not has_structured:
                continue
            # Validate types before assignment (LLM output is untrusted)
            source = item.get("source")
            sink = item.get("sink")
            data_flow = item.get("data_flow")
            if source and not isinstance(source, str):
                source = str(source)
            if source:
                # Sanitize prompt injection only — do NOT html.escape stored values;
                # consumers expect raw strings, not HTML entities (e.g. &#x27;).
                source = PromptSanitizer.escape_prompt_injection(source)

            if sink and not isinstance(sink, str):
                sink = str(sink)
            if sink:
                sink = PromptSanitizer.escape_prompt_injection(sink)

            if data_flow and not isinstance(data_flow, list):
                data_flow = []
            else:
                data_flow = [PromptSanitizer.escape_prompt_injection(str(x)) for x in (data_flow or [])]
            item["_machine_context"] = {
                "source": source,
                "sink": sink,
                "data_flow_path": data_flow,
            }
