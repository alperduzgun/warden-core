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

    async def analyze_security_async(self, code_content: str, language: str, use_fast_tier: bool = False) -> dict:
        """
        Analyze code for security vulnerabilities using LLM.

        Default implementation uses complete_async with a standard prompt.
        Providers may override this for specialized models or parameters.

        Args:
            code_content: Source code to analyze
            language: Language of the code

        Returns:
            Dict containing findings list
        """
        from warden.shared.utils.json_parser import parse_json_from_llm
        from warden.shared.utils.llm_context import BUDGET_SECURITY, prepare_code_for_llm, resolve_token_budget

        budget = resolve_token_budget(BUDGET_SECURITY)
        truncated_code = prepare_code_for_llm(code_content, token_budget=budget)

        prompt = f"""Analyze this {language} code for security vulnerabilities. Focus on exploitable flaws only.

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

ALSO CHECK: SQL Injection, XSS, Hardcoded Secrets, SSRF, Command Injection, Path Traversal, IDOR.
IDOR: endpoint uses user-controlled ID without ownership check (parameterized query alone is NOT enough).

IMPORTANT: Output ONLY valid JSON. No markdown. Keep detail field brief (1 sentence).
{{"findings":[{{"severity":"critical|high|medium","message":"Short description","line_number":1,"detail":"Brief exploit explanation"}}]}}
If no issues: {{"findings":[]}}

```{language}
{truncated_code}
```"""

        from warden.llm.prompts.tool_instructions import (
            get_tool_enhanced_prompt,
        )

        security_system_prompt = get_tool_enhanced_prompt("You are a strict security auditor. Output valid JSON only.")

        try:
            response = await self.complete_async(
                prompt,
                system_prompt=security_system_prompt,
                use_fast_tier=use_fast_tier,
            )
            if not response.success:
                logger.warning("analyze_security_llm_failed", reason="response.success=False", content_preview=str(response.content)[:300] if response.content else "None")
                return {"findings": []}

            logger.debug("analyze_security_raw_response", content_length=len(response.content) if response.content else 0, content_preview=str(response.content)[:500] if response.content else "None")

            parsed = parse_json_from_llm(response.content)
            if not parsed:
                logger.warning("analyze_security_parse_failed", content_preview=str(response.content)[:500] if response.content else "None")
                return {"findings": []}

            logger.debug("analyze_security_parsed", findings_count=len(parsed.get("findings", [])))

            # Enrich findings with MachineContext from structured LLM output
            self._enrich_findings_from_llm(parsed)
            return parsed
        except (json.JSONDecodeError, ValueError, KeyError) as exc:
            logger.warning("analyze_security_exception", error=str(exc), content_preview=str(response.content)[:500] if 'response' in dir() else "no_response")
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
