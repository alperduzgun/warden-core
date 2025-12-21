"""
OpenAI GPT LLM Client (supports both OpenAI and Azure OpenAI)

Based on C# OpenAIClient.cs
"""

import httpx
import time
from ..config import ProviderConfig
from ..types import LlmProvider, LlmRequest, LlmResponse
from .base import ILlmClient


class OpenAIClient(ILlmClient):
    """OpenAI GPT client - supports both OpenAI and Azure OpenAI"""

    def __init__(self, config: ProviderConfig, provider: LlmProvider = LlmProvider.OPENAI):
        if not config.api_key:
            raise ValueError(f"{provider.value} API key is required")

        self._api_key = config.api_key
        self._provider = provider
        self._default_model = config.default_model or "gpt-4o"

        # Azure vs OpenAI endpoints
        if provider == LlmProvider.AZURE_OPENAI:
            if not config.endpoint:
                raise ValueError("Azure OpenAI endpoint is required")
            self._base_url = config.endpoint.rstrip("/")
            self._api_version = config.api_version or "2024-02-01"
        else:
            self._base_url = config.endpoint or "https://api.openai.com/v1"

    @property
    def provider(self) -> LlmProvider:
        return self._provider

    async def send_async(self, request: LlmRequest) -> LlmResponse:
        start_time = time.time()

        try:
            headers = {"Content-Type": "application/json"}

            # Azure uses api-key header, OpenAI uses Authorization
            if self._provider == LlmProvider.AZURE_OPENAI:
                headers["api-key"] = self._api_key
                url = f"{self._base_url}/openai/deployments/{request.model or self._default_model}/chat/completions?api-version={self._api_version}"
            else:
                headers["Authorization"] = f"Bearer {self._api_key}"
                url = f"{self._base_url}/chat/completions"

            payload = {
                "messages": [
                    {"role": "system", "content": request.system_prompt},
                    {"role": "user", "content": request.user_message}
                ],
                "temperature": request.temperature,
                "max_tokens": request.max_tokens,
                "response_format": {"type": "json_object"}  # Force JSON response
            }

            if self._provider != LlmProvider.AZURE_OPENAI:
                payload["model"] = request.model or self._default_model

            async with httpx.AsyncClient(timeout=request.timeout_seconds) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                result = response.json()

            duration_ms = int((time.time() - start_time) * 1000)

            if not result.get("choices"):
                return LlmResponse(
                    content="",
                    success=False,
                    error_message="No response from OpenAI",
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
        """
        Check if provider is available.

        For Azure OpenAI, just check if credentials are configured.
        Making a test API call would waste tokens and time.
        """
        try:
            # Just verify we have the necessary credentials
            if self._provider == LlmProvider.AZURE_OPENAI:
                return bool(self._api_key and self._base_url)
            else:
                return bool(self._api_key)
        except:
            return False
