"""
Gemini LLM Client

Direct integration with Google Generative Language API via HTTPX.
Avoids heavy dependencies like google-generativeai.
"""

import time
from typing import Any

import httpx

from warden.shared.infrastructure.resilience import resilient

from ..config import ProviderConfig
from ..registry import ProviderRegistry
from ..types import LlmProvider, LlmRequest, LlmResponse
from .base import ILlmClient


class GeminiClient(ILlmClient):
    """
    Google Gemini LLM client (REST API).
    """

    def __init__(self, config: ProviderConfig):
        """
        Initialize Gemini client.

        Args:
            config: Provider configuration
        """
        if not config.api_key:
            raise ValueError("Gemini API key is required")

        self._api_key = config.api_key
        # Default to 1.5 flash as it's efficient
        self._default_model = config.default_model or "gemini-1.5-flash"
        self._base_url = "https://generativelanguage.googleapis.com/v1beta/models"

    @property
    def provider(self) -> LlmProvider:
        return LlmProvider.GEMINI

    @resilient(name="provider_send", timeout_seconds=60.0)
    async def send_async(self, request: LlmRequest) -> LlmResponse:
        """
        Send request to Gemini API.
        """
        start_time = time.time()
        model = request.model or self._default_model

        # Gemini API format
        # https://ai.google.dev/api/rest/v1/models/generateContent
        # Note: API key is sent via header (not URL parameter) for security
        url = f"{self._base_url}/{model}:generateContent"

        # Construct payload
        # System instructions are supported in 1.5 models via system_instruction
        payload: dict[str, Any] = {
            "contents": [{"parts": [{"text": request.user_message}]}],
            "generationConfig": {
                "temperature": request.temperature,
                "maxOutputTokens": request.max_tokens,
            },
        }

        # Add system prompt if present
        if request.system_prompt:
            payload["systemInstruction"] = {"parts": [{"text": request.system_prompt}]}

        try:
            from warden.llm.global_rate_limiter import GlobalRateLimiter

            limiter = await GlobalRateLimiter.get_instance()
            await limiter.acquire("gemini", tokens=request.max_tokens)

            # Prepare headers with API key (secure method)
            headers = {"Content-Type": "application/json", "x-goog-api-key": self._api_key}

            async with httpx.AsyncClient(timeout=request.timeout_seconds) as client:
                response = await client.post(url, json=payload, headers=headers)

                if response.status_code != 200:
                    response.raise_for_status()

                result = response.json()

            duration_ms = int((time.time() - start_time) * 1000)

            # Extract content
            # Response: { candidates: [ { content: { parts: [ { text: "..." } ] } } ] }
            content = ""
            if result.get("candidates"):
                candidate = result["candidates"][0]
                if "content" in candidate and "parts" in candidate["content"]:
                    parts = candidate["content"]["parts"]
                    content = "".join([p.get("text", "") for p in parts])

            if not content:
                # Check for safety ratings blocking
                return LlmResponse(
                    content="",
                    success=False,
                    error_message=f"No content generated. Response: {result}",
                    provider=self.provider,
                    duration_ms=duration_ms,
                )

            # Token usage
            usage = result.get("usageMetadata", {})

            return LlmResponse(
                content=content,
                success=True,
                provider=self.provider,
                model=model,
                prompt_tokens=usage.get("promptTokenCount"),
                completion_tokens=usage.get("candidatesTokenCount"),
                total_tokens=usage.get("totalTokenCount"),
                duration_ms=duration_ms,
            )

        except httpx.HTTPStatusError as e:
            duration_ms = int((time.time() - start_time) * 1000)
            return LlmResponse(
                content="",
                success=False,
                error_message=f"HTTP {e.response.status_code}: {(e.response.text[:200] if e.response.text else 'No response body')}",
                provider=self.provider,
                duration_ms=duration_ms,
            )

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            return LlmResponse(
                content="", success=False, error_message=str(e), provider=self.provider, duration_ms=duration_ms
            )

    async def is_available_async(self) -> bool:
        """Check availability."""
        try:
            test_req = LlmRequest(system_prompt="hi", user_message="hi", max_tokens=10)
            resp = await self.send_async(test_req)
            return resp.success
        except httpx.TimeoutException:
            return False
        except httpx.ConnectError:
            return False
        except httpx.HTTPStatusError:
            return False
        except ValueError:
            return False


# Self-register with the registry
ProviderRegistry.register(LlmProvider.GEMINI, GeminiClient)
