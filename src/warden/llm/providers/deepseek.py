"""
DeepSeek Coder LLM Client

Based on C# DeepSeekClient.cs
API: https://api.deepseek.com
"""

import httpx
import time
from ..config import ProviderConfig
from ..types import LlmProvider, LlmRequest, LlmResponse
from .base import ILlmClient


class DeepSeekClient(ILlmClient):
    """DeepSeek Coder client - OpenAI-compatible API"""

    def __init__(self, config: ProviderConfig):
        if not config.api_key:
            raise ValueError("DeepSeek API key is required")

        self._api_key = config.api_key
        self._default_model = config.default_model or "deepseek-coder"
        self._base_url = config.endpoint or "https://api.deepseek.com"

    @property
    def provider(self) -> LlmProvider:
        return LlmProvider.DEEPSEEK

    async def send_async(self, request: LlmRequest) -> LlmResponse:
        start_time = time.time()

        try:
            headers = {
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json"
            }

            payload = {
                "model": request.model or self._default_model,
                "messages": [
                    {"role": "system", "content": request.system_prompt},
                    {"role": "user", "content": request.user_message}
                ],
                "temperature": request.temperature,
                "max_tokens": request.max_tokens
            }

            async with httpx.AsyncClient(timeout=request.timeout_seconds) as client:
                response = await client.post(
                    f"{self._base_url}/v1/chat/completions",
                    headers=headers,
                    json=payload
                )
                response.raise_for_status()
                result = response.json()

            duration_ms = int((time.time() - start_time) * 1000)

            if not result.get("choices"):
                return LlmResponse(
                    content="",
                    success=False,
                    error_message="No response from DeepSeek",
                    provider=self.provider,
                    duration_ms=duration_ms
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
                duration_ms=duration_ms
            )

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            return LlmResponse(
                content="",
                success=False,
                error_message=str(e),
                provider=self.provider,
                duration_ms=duration_ms
            )

    async def is_available_async(self) -> bool:
        try:
            test_request = LlmRequest(
                system_prompt="You are a helpful assistant.",
                user_message="Hi",
                max_tokens=10,
                timeout_seconds=10
            )
            response = await self.send_async(test_request)
            return response.success
        except:
            return False
