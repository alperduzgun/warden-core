"""
Anthropic Claude LLM Client

Based on C# AnthropicClient.cs:
/Users/alper/vibe-code-analyzer/src/Warden.LLM/Providers/AnthropicClient.cs

API Documentation: https://docs.anthropic.com/claude/reference
"""

import httpx
import time
from typing import Optional

from ..config import ProviderConfig
from ..types import LlmProvider, LlmRequest, LlmResponse
from .base import ILlmClient


class AnthropicClient(ILlmClient):
    """
    Anthropic Claude LLM client

    Matches C# AnthropicClient implementation
    Supports Claude 3.5 Sonnet and other models
    """

    def __init__(self, config: ProviderConfig):
        """
        Initialize Anthropic client

        Args:
            config: Provider configuration with API key and model

        Raises:
            ValueError: If API key is missing
        """
        if not config.api_key:
            raise ValueError("Anthropic API key is required")

        self._api_key = config.api_key
        self._default_model = config.default_model or "claude-3-5-sonnet-20241022"
        self._base_url = config.endpoint or "https://api.anthropic.com"

    @property
    def provider(self) -> LlmProvider:
        return LlmProvider.ANTHROPIC

    async def send_async(self, request: LlmRequest) -> LlmResponse:
        """
        Send request to Anthropic API

        Args:
            request: LLM request parameters

        Returns:
            LLM response with content or error (never raises)
        """
        start_time = time.time()

        try:
            headers = {
                "x-api-key": self._api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            }

            payload = {
                "model": request.model or self._default_model,
                "system": request.system_prompt,
                "messages": [
                    {"role": "user", "content": request.user_message}
                ],
                "temperature": request.temperature,
                "max_tokens": request.max_tokens
            }

            async with httpx.AsyncClient(timeout=request.timeout_seconds) as client:
                response = await client.post(
                    f"{self._base_url}/v1/messages",
                    headers=headers,
                    json=payload
                )
                response.raise_for_status()
                result = response.json()

            duration_ms = int((time.time() - start_time) * 1000)

            # Validate response structure
            if not result.get("content"):
                return LlmResponse(
                    content="",
                    success=False,
                    error_message="No response from Anthropic",
                    provider=self.provider,
                    duration_ms=duration_ms
                )

            # Extract usage information
            usage = result.get("usage", {})

            return LlmResponse(
                content=result["content"][0]["text"],
                success=True,
                provider=self.provider,
                model=result.get("model"),
                prompt_tokens=usage.get("input_tokens"),
                completion_tokens=usage.get("output_tokens"),
                total_tokens=usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
                duration_ms=duration_ms
            )

        except httpx.HTTPStatusError as e:
            duration_ms = int((time.time() - start_time) * 1000)
            error_msg = f"HTTP {e.response.status_code}: {e.response.text}"
            return LlmResponse(
                content="",
                success=False,
                error_message=error_msg,
                provider=self.provider,
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
        Check if Anthropic is available

        Returns:
            True if provider is ready, False otherwise (never raises)
        """
        try:
            test_request = LlmRequest(
                system_prompt="You are a helpful assistant.",
                user_message="Hi",
                max_tokens=10,
                timeout_seconds=10  # Short timeout for availability check
            )

            response = await self.send_async(test_request)
            return response.success

        except:
            return False
