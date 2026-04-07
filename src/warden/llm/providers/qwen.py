"""
Qwen LLM Client (Alibaba Cloud DashScope)

OpenAI-compatible API endpoint.
API: https://dashscope.aliyuncs.com/compatible-mode/v1
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


def _parse_retry_after(response: httpx.Response) -> int:
    """
    Extract wait time from a Qwen 429 response.

    Checks the standard ``Retry-After`` header first.
    Falls back to a conservative 60-second default if absent.

    Returns seconds to wait.
    """
    header = response.headers.get("retry-after")
    if header and header.isdigit():
        return int(header)
    return 60  # Qwen default back-off when no header is present


class QwenClient(ILlmClient):
    """Qwen (Alibaba Cloud DashScope) client — OpenAI-compatible API"""

    # Class-level rate-limit timestamp shared across instances
    _rate_limited_until: float = 0.0

    def __init__(self, config: ProviderConfig):
        if not config.api_key:
            raise ValueError("Qwen API key is required")

        self._api_key = config.api_key
        self._default_model = config.default_model or "qwen-coder-plus"
        self._base_url = config.endpoint or "https://dashscope.aliyuncs.com/compatible-mode/v1"

    @property
    def provider(self) -> LlmProvider:
        return LlmProvider.QWEN_CLOUD

    @resilient(name="provider_send", timeout_seconds=90.0)
    async def send_async(self, request: LlmRequest) -> LlmResponse:
        start_time = time.time()

        # Short-circuit if we know we are rate-limited.
        # CHAOS-SAFE: never sleep longer than the request's timeout budget.
        remaining = QwenClient._rate_limited_until - time.time()
        if remaining > 0:
            if remaining > request.timeout_seconds:
                logger.info(
                    "qwen_rate_limited_skip",
                    remaining_seconds=round(remaining, 1),
                    reason="exceeds_timeout_budget",
                )
                return LlmResponse.error(
                    f"Qwen rate limited — {remaining:.0f}s remaining, exceeds timeout budget",
                    provider=self.provider,
                )
            logger.info("qwen_rate_limited_backoff", wait_seconds=round(remaining, 1))
            await asyncio.sleep(remaining)

        try:
            from warden.llm.global_rate_limiter import GlobalRateLimiter

            limiter = await GlobalRateLimiter.get_instance()
            try:
                await limiter.acquire("qwen_cloud", tokens=request.max_tokens + request.estimated_prompt_tokens)
            except asyncio.TimeoutError:
                return LlmResponse.error(
                    "Qwen rate-limit queue timeout — provider skipped",
                    provider=self.provider,
                )

            headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}

            model = request.model or self._default_model

            payload: dict = {
                "model": model,
                "messages": [
                    {"role": "system", "content": request.system_prompt},
                    {"role": "user", "content": request.user_message},
                ],
                "temperature": request.temperature,
                "max_tokens": request.max_tokens,
            }

            # Enforce JSON output when prompt requests it (DashScope supports response_format)
            _sys = (request.system_prompt or "").lower()
            _msg = (request.user_message or "").lower()
            if "json" in _sys or "json" in _msg[:200] or "json" in _msg[-400:]:
                payload["response_format"] = {"type": "json_object"}

            async with httpx.AsyncClient(timeout=request.timeout_seconds) as client:
                response = await client.post(f"{self._base_url}/chat/completions", headers=headers, json=payload)
                response.raise_for_status()
                result = response.json()

            duration_ms = LlmResponse.elapsed_ms(start_time)

            if not result.get("choices"):
                return LlmResponse.error("No response from Qwen", provider=self.provider, duration_ms=duration_ms)

            usage = result.get("usage", {})

            return LlmResponse(
                content=result["choices"][0]["message"]["content"],
                success=True,
                provider=self.provider,
                model=result.get("model") or model,
                prompt_tokens=usage.get("prompt_tokens"),
                completion_tokens=usage.get("completion_tokens"),
                total_tokens=usage.get("total_tokens"),
                duration_ms=duration_ms,
            )

        except httpx.HTTPStatusError as e:
            duration_ms = LlmResponse.elapsed_ms(start_time)
            body = e.response.text[:500] if e.response else ""

            if e.response is not None and e.response.status_code == 429:
                retry_after = _parse_retry_after(e.response)
                QwenClient._rate_limited_until = time.time() + retry_after
                logger.info(
                    "qwen_rate_limited",
                    retry_after_seconds=retry_after,
                    rate_limited_until=QwenClient._rate_limited_until,
                )
                logger.debug("qwen_429_body", body=body)
                return LlmResponse.error(
                    f"Qwen rate limited (429) — retry after {retry_after}s",
                    provider=self.provider,
                    duration_ms=duration_ms,
                )

            return LlmResponse.error(f"{e} | body={body}", provider=self.provider, duration_ms=duration_ms)
        except Exception as e:
            duration_ms = LlmResponse.elapsed_ms(start_time)
            return LlmResponse.error(str(e), provider=self.provider, duration_ms=duration_ms)

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
ProviderRegistry.register(LlmProvider.QWEN_CLOUD, QwenClient)
