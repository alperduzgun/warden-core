"""
QwenCode LLM Client (Alibaba Cloud)

Based on C# QwenCodeClient.cs
API: https://dashscope.aliyuncs.com
"""

import time

import httpx

from warden.shared.infrastructure.resilience import resilient

from ..config import ProviderConfig
from ..registry import ProviderRegistry
from ..types import LlmProvider, LlmRequest, LlmResponse
from .base import ILlmClient


class QwenCodeClient(ILlmClient):
    """QwenCode client - Alibaba Cloud DashScope API"""

    def __init__(self, config: ProviderConfig):
        if not config.api_key:
            raise ValueError("QwenCode API key is required")

        self._api_key = config.api_key
        self._default_model = config.default_model or "qwen2.5-coder-32b-instruct"
        self._base_url = config.endpoint or "https://dashscope.aliyuncs.com"

    @property
    def provider(self) -> LlmProvider:
        return LlmProvider.QWENCODE

    @resilient(name="provider_send", timeout_seconds=60.0)
    async def send_async(self, request: LlmRequest) -> LlmResponse:
        start_time = time.time()

        try:
            from warden.llm.global_rate_limiter import GlobalRateLimiter

            limiter = await GlobalRateLimiter.get_instance()
            await limiter.acquire("qwen", tokens=request.max_tokens + request.estimated_prompt_tokens)

            headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}

            # Auto-detect JSON mode from prompt content
            _sys_lower = (request.system_prompt or "").lower()
            _msg_lower = (request.user_message or "").lower()
            _wants_json = "json" in _sys_lower or "json" in _msg_lower[:200] or "json" in _msg_lower[-400:]

            payload = {
                "model": request.model or self._default_model,
                "input": {
                    "messages": [
                        {"role": "system", "content": request.system_prompt},
                        {"role": "user", "content": request.user_message},
                    ]
                },
                "parameters": {"temperature": request.temperature, "max_tokens": request.max_tokens},
            }
            if _wants_json:
                payload["parameters"]["result_format"] = "message"

            async with httpx.AsyncClient(timeout=request.timeout_seconds) as client:
                response = await client.post(
                    f"{self._base_url}/api/v1/services/aigc/text-generation/generation", headers=headers, json=payload
                )
                response.raise_for_status()
                result = response.json()

            duration_ms = LlmResponse.elapsed_ms(start_time)

            # DashScope returns different shapes depending on result_format:
            # - text format (default): output.text
            # - message format: output.choices[0].message.content
            output = result.get("output", {})
            content_text = output.get("text")
            if not content_text and "choices" in output:
                choices = output["choices"]
                if choices and isinstance(choices, list):
                    content_text = choices[0].get("message", {}).get("content")

            if not content_text:
                return LlmResponse.error("No response from QwenCode", provider=self.provider, duration_ms=duration_ms)

            usage = result.get("usage", {})

            return LlmResponse(
                content=content_text,
                success=True,
                provider=self.provider,
                model=request.model or self._default_model,
                prompt_tokens=usage.get("input_tokens"),
                completion_tokens=usage.get("output_tokens"),
                total_tokens=usage.get("total_tokens"),
                duration_ms=duration_ms,
            )

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
            return False
        except httpx.ConnectError:
            return False
        except httpx.HTTPStatusError:
            return False
        except ValueError:
            return False


# Self-register with the registry
ProviderRegistry.register(LlmProvider.QWENCODE, QwenCodeClient)
