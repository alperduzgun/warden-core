"""
Ollama LLM Client (Local Model Support)

API: http://localhost:11434/api/chat
Uses streaming mode so long CPU-side generation does not hit read timeouts.
"""

import json
import time

import httpx

from warden.shared.infrastructure.logging import get_logger
from warden.shared.infrastructure.resilience import resilient

from ..config import ProviderConfig
from ..registry import ProviderRegistry
from ..types import LlmProvider, LlmRequest, LlmResponse
from .base import ILlmClient

logger = get_logger(__name__)


class ModelNotFoundError(Exception):
    """Raised when the requested Ollama model is not installed (HTTP 404).

    This is a permanent failure — retrying won't help.
    """

    non_retryable = True


class OllamaClient(ILlmClient):
    """
    Ollama client for local LLM execution.
    Targeting ultra-light models like qwen2.5-coder:3b for CI and fast checks.
    """

    def __init__(self, config: ProviderConfig):
        # Ollama doesn't require an API key by default
        self._endpoint = config.endpoint or "http://localhost:11434"
        self._default_model = config.default_model or "qwen2.5-coder:3b"
        # Cache of models confirmed missing — prevents repeated 404s
        self._missing_models: set[str] = set()

        logger.debug("ollama_client_initialized", endpoint=self._endpoint, default_model=self._default_model)

    @property
    def provider(self) -> LlmProvider:
        return LlmProvider.OLLAMA

    @resilient(name="provider_send", timeout_seconds=300.0, retry_max_attempts=2)
    async def send_async(self, request: LlmRequest) -> LlmResponse:
        """
        Send a request to the local Ollama instance.
        Uses the chat API for consistency with other providers.
        """
        start_time = time.time()
        model = request.model or self._default_model

        # Fail-fast: skip rate limiter + HTTP call for known-missing models
        if model in self._missing_models:
            return LlmResponse(
                content="",
                success=False,
                error_message=f"Model '{model}' not found. Run 'ollama pull {model}'.",
                provider=self.provider,
                duration_ms=0,
            )

        try:
            from warden.llm.global_rate_limiter import GlobalRateLimiter

            limiter = await GlobalRateLimiter.get_instance()
            await limiter.acquire("ollama", tokens=request.max_tokens)

            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": request.system_prompt},
                    {"role": "user", "content": request.user_message},
                ],
                "stream": True,
                "options": {"temperature": request.temperature, "num_predict": request.max_tokens},
            }

            # Streaming: Ollama sends tokens as they are generated.
            # read_timeout applies per-chunk (between tokens), NOT total generation time.
            # For larger models (3b+) on CPU, prefill alone can exceed 60s before the
            # first token appears — so we use 120s to accommodate slow prefill phases.
            stream_timeout = httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=5.0)
            content_parts: list[str] = []
            prompt_tokens = 0
            completion_tokens = 0

            async with httpx.AsyncClient(timeout=stream_timeout) as client:
                async with client.stream("POST", f"{self._endpoint}/api/chat", json=payload) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        chunk = json.loads(line)
                        if "message" in chunk and "content" in chunk["message"]:
                            content_parts.append(chunk["message"]["content"])
                        if chunk.get("done"):
                            prompt_tokens = chunk.get("prompt_eval_count", 0)
                            completion_tokens = chunk.get("eval_count", 0)
                            break

            duration_ms = int((time.time() - start_time) * 1000)
            content = "".join(content_parts)

            return LlmResponse(
                content=content,
                success=True,
                provider=self.provider,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                duration_ms=duration_ms,
            )

        except httpx.HTTPStatusError as e:
            duration_ms = int((time.time() - start_time) * 1000)
            if e.response.status_code == 404:
                # Cache the missing model to fail-fast on subsequent calls
                self._missing_models.add(model)
                error_msg = f"Model '{model}' not found. Run 'ollama pull {model}'."
                logger.error("ollama_model_not_found", model=model, duration_ms=duration_ms)
                # Raise non-retryable error to prevent retry/timeout overhead
                raise ModelNotFoundError(error_msg) from e

            error_msg = str(e)
            logger.error(
                "ollama_request_failed",
                status_code=e.response.status_code,
                error=error_msg,
                model=model,
                duration_ms=duration_ms,
            )
            return LlmResponse(
                content="", success=False, error_message=error_msg, provider=self.provider, duration_ms=duration_ms
            )
        except ModelNotFoundError:
            raise  # Don't wrap in generic handler
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error("ollama_request_failed", error=str(e), model=model, duration_ms=duration_ms)
            return LlmResponse(
                content="", success=False, error_message=str(e), provider=self.provider, duration_ms=duration_ms
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
                    exists = any(
                        self._default_model == name or f"{self._default_model}:latest" == name for name in model_names
                    )
                    if not exists:
                        logger.warning("ollama_model_missing", required=self._default_model, available=model_names)
                        return False

                return True
        except Exception as e:
            logger.debug("ollama_availability_error", error=str(e))
            return False


# Self-register with the registry
ProviderRegistry.register(LlmProvider.OLLAMA, OllamaClient)
