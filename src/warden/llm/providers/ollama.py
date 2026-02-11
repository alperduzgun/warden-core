"""
Ollama LLM Client (Local Model Support)

API: http://localhost:11434/api/chat
"""

import time

import httpx

from warden.shared.infrastructure.logging import get_logger
from warden.shared.infrastructure.resilience import resilient

from ..config import ProviderConfig
from ..registry import ProviderRegistry
from ..types import LlmProvider, LlmRequest, LlmResponse
from .base import ILlmClient

logger = get_logger(__name__)


class OllamaClient(ILlmClient):
    """
    Ollama client for local LLM execution.
    Targeting ultra-light models like qwen2.5-coder:0.5b for CI and fast checks.
    """

    def __init__(self, config: ProviderConfig):
        # Ollama doesn't require an API key by default
        self._endpoint = config.endpoint or "http://localhost:11434"
        self._default_model = config.default_model or "qwen2.5-coder:0.5b"

        logger.debug(
            "ollama_client_initialized",
            endpoint=self._endpoint,
            default_model=self._default_model
        )

    @property
    def provider(self) -> LlmProvider:
        return LlmProvider.OLLAMA

    @resilient(name="provider_send", timeout_seconds=60.0)
    async def send_async(self, request: LlmRequest) -> LlmResponse:
        """
        Send a request to the local Ollama instance.
        Uses the chat API for consistency with other providers.
        """
        start_time = time.time()
        model = request.model or self._default_model

        try:
            from warden.llm.global_rate_limiter import GlobalRateLimiter
            limiter = await GlobalRateLimiter.get_instance()
            await limiter.acquire("ollama", tokens=request.max_tokens)

            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": request.system_prompt},
                    {"role": "user", "content": request.user_message}
                ],
                "stream": False,
                "options": {
                    "temperature": request.temperature,
                    "num_predict": request.max_tokens
                }
            }

            async with httpx.AsyncClient(timeout=request.timeout_seconds) as client:
                response = await client.post(
                    f"{self._endpoint}/api/chat",
                    json=payload
                )
                response.raise_for_status()
                result = response.json()

            duration_ms = int((time.time() - start_time) * 1000)
            content = result.get("message", {}).get("content", "")

            # Ollama provides token counts in prompt_eval_count and eval_count
            prompt_tokens = result.get("prompt_eval_count", 0)
            completion_tokens = result.get("eval_count", 0)

            return LlmResponse(
                content=content,
                success=True,
                provider=self.provider,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                duration_ms=duration_ms
            )

        except httpx.HTTPStatusError as e:
            duration_ms = int((time.time() - start_time) * 1000)
            error_msg = str(e)
            if e.response.status_code == 404:
                error_msg = f"Model '{model}' NOT FOUND on this Ollama instance. Please run 'ollama pull {model}'."

            logger.error(
                "ollama_request_failed",
                status_code=e.response.status_code,
                error=error_msg,
                model=model,
                duration_ms=duration_ms
            )
            return LlmResponse(
                content="",
                success=False,
                error_message=error_msg,
                provider=self.provider,
                duration_ms=duration_ms
            )
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(
                "ollama_request_failed",
                error=str(e),
                model=model,
                duration_ms=duration_ms
            )
            return LlmResponse(
                content="",
                success=False,
                error_message=str(e),
                provider=self.provider,
                duration_ms=duration_ms
            )

    async def is_available_async(self) -> bool:
        """
        Check if Ollama is running and responsive, AND the default model is pulled.
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # 1. Check if Ollama is running
                response = await client.get(self._endpoint)
                if response.status_code != 200:
                    return False

                # 2. Check if the model exists
                tags_response = await client.get(f"{self._endpoint}/api/tags")
                if tags_response.status_code == 200:
                    models = tags_response.json().get("models", [])
                    model_names = [m.get("name") for m in models]

                    # Exact match or tag-less match
                    exists = any(self._default_model == name or f"{self._default_model}:latest" == name for name in model_names)
                    if not exists:
                        logger.warning(
                            "ollama_model_missing",
                            required=self._default_model,
                            available=model_names
                        )
                        return False

                return True
        except Exception as e:
            logger.debug("ollama_availability_error", error=str(e))
            return False


# Self-register with the registry
ProviderRegistry.register(LlmProvider.OLLAMA, OllamaClient)
