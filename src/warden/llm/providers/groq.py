"""
Groq LLM Client

Based on C# GroqClient.cs
API: https://api.groq.com
"""

import asyncio
import time

import httpx
import structlog

from warden.shared.infrastructure.resilience import resilient

from ..config import ProviderConfig
from ..registry import ProviderRegistry
from ..types import LlmProvider, LlmRequest, LlmResponse
from .base import ILlmClient

logger = structlog.get_logger(__name__)


class GroqClient(ILlmClient):
    """Groq client - Fast inference API"""

    # Class-level rate-limit timestamp shared across instances
    _rate_limited_until: float = 0.0

    def __init__(self, config: ProviderConfig):
        if not config.api_key:
            raise ValueError("Groq API key is required")

        self._api_key = config.api_key
        self._default_model = config.default_model or "llama-3.3-70b-versatile"
        self._base_url = config.endpoint or "https://api.groq.com/openai/v1"

    @property
    def provider(self) -> LlmProvider:
        return LlmProvider.GROQ

    @resilient(name="provider_send", timeout_seconds=90.0)
    async def send_async(self, request: LlmRequest) -> LlmResponse:
        start_time = time.time()

        # Short-circuit if we know we are rate-limited
        remaining = GroqClient._rate_limited_until - time.time()
        if remaining > 0:
            logger.info("groq_rate_limited_backoff", wait_seconds=round(remaining, 1))
            await asyncio.sleep(remaining)

        try:
            from warden.llm.global_rate_limiter import GlobalRateLimiter

            limiter = await GlobalRateLimiter.get_instance()
            await limiter.acquire("groq", tokens=request.max_tokens)

            headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}

            # Use requested model only if it looks like a Groq-compatible model.
            # Reject models that belong to other providers:
            #   - "claude-*"         → Anthropic/Claude Code models
            #   - "gpt-*"            → OpenAI models
            #   - "name:tag" format  → Ollama local models (e.g. "qwen2.5-coder:3b")
            model = (
                request.model
                if request.model and not request.model.startswith(("claude", "gpt-")) and ":" not in request.model
                else self._default_model
            )

            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": request.system_prompt},
                    {"role": "user", "content": request.user_message},
                ],
                "temperature": request.temperature,
                "max_tokens": request.max_tokens,
            }

            async with httpx.AsyncClient(timeout=request.timeout_seconds) as client:
                response = await client.post(f"{self._base_url}/chat/completions", headers=headers, json=payload)
                response.raise_for_status()
                result = response.json()

            duration_ms = int((time.time() - start_time) * 1000)

            if not result.get("choices"):
                return LlmResponse(
                    content="",
                    success=False,
                    error_message="No response from Groq",
                    provider=self.provider,
                    duration_ms=duration_ms,
                )

            usage = result.get("usage", {})

            return LlmResponse(
                content=result["choices"][0]["message"]["content"],
                success=True,
                provider=self.provider,
                model=result.get("model"),
                prompt_tokens=usage.get("prompt_tokens"),
                completion_tokens=usage.get("completion_tokens"),
                total_tokens=usage.get("total_tokens"),
                duration_ms=duration_ms,
            )

        except httpx.HTTPStatusError as e:
            duration_ms = int((time.time() - start_time) * 1000)
            body = e.response.text[:500] if e.response else ""

            if e.response is not None and e.response.status_code == 429:
                retry_after = int(e.response.headers.get("retry-after", 5))
                GroqClient._rate_limited_until = time.time() + retry_after
                logger.info(
                    "groq_rate_limited",
                    retry_after_seconds=retry_after,
                    rate_limited_until=GroqClient._rate_limited_until,
                )
                return LlmResponse(
                    content="",
                    success=False,
                    error_message=f"Groq rate limited (429) — retry after {retry_after}s | body={body}",
                    provider=self.provider,
                    duration_ms=duration_ms,
                )

            return LlmResponse(
                content="",
                success=False,
                error_message=f"{e} | body={body}",
                provider=self.provider,
                duration_ms=duration_ms,
            )
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            return LlmResponse(
                content="", success=False, error_message=str(e), provider=self.provider, duration_ms=duration_ms
            )

    async def is_available_async(self) -> bool:
        try:
            test_request = LlmRequest(
                system_prompt="You are a helpful assistant.", user_message="Hi", max_tokens=10, timeout_seconds=10
            )
            response = await self.send_async(test_request)
            return response.success
        except httpx.TimeoutException:
            # Network timeout - provider may be slow or unreachable
            return False
        except httpx.ConnectError:
            # Connection failed - provider endpoint unreachable
            return False
        except httpx.HTTPStatusError:
            # HTTP error (4xx/5xx) - auth or server issue
            return False
        except ValueError:
            # Configuration or validation error
            return False


# Self-register with the registry
ProviderRegistry.register(LlmProvider.GROQ, GroqClient)
