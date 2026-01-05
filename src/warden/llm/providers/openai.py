"""
OpenAI GPT LLM Client (supports both OpenAI and Azure OpenAI)

Based on C# OpenAIClient.cs
"""

import httpx
import time
import json
from typing import Dict, Any, AsyncGenerator

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
                "max_tokens": request.max_tokens
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

        except (httpx.HTTPStatusError, httpx.RequestError) as e:
            duration_ms = int((time.time() - start_time) * 1000)
            return LlmResponse(
                content="",
                success=False,
                error_message=f"HTTP error: {str(e)}",
                provider=self.provider,
                duration_ms=duration_ms
            )
        except (json.JSONDecodeError, KeyError) as e:
            duration_ms = int((time.time() - start_time) * 1000)
            return LlmResponse(
                content="",
                success=False,
                error_message=f"JSON/Data error: {str(e)}",
                provider=self.provider,
                duration_ms=duration_ms
            )
        except Exception as e:
            # Last resort for truly unexpected errors
            duration_ms = int((time.time() - start_time) * 1000)
            return LlmResponse(
                content="",
                success=False,
                error_message=f"Unexpected error: {str(e)}",
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
        except (ValueError, AttributeError):
            return False

    async def complete_async(self, prompt: str, system_prompt: str = "You are a helpful coding assistant.") -> LlmResponse:
        """
        Simple completion method for non-streaming requests.

        Args:
            prompt: User prompt
            system_prompt: System prompt (optional)

        Returns:
            LlmResponse object with content and token usage

        Raises:
            Exception: If request fails
        """
        request = LlmRequest(
            user_message=prompt,
            system_prompt=system_prompt,
            model=self._default_model,
            temperature=0.7,
            max_tokens=2000,
            timeout_seconds=30.0
        )

        response = await self.send_async(request)

        if not response.success:
            raise Exception(f"LLM request failed: {response.error_message}")

        return response

    async def stream_completion(self, prompt: str, system_prompt: str = "You are a helpful coding assistant."):
        """
        Streaming completion method.

        Args:
            prompt: User prompt
            system_prompt: System prompt (optional)

        Yields:
            Completion chunks as they arrive

        Note:
            OpenAI streaming requires SSE parsing. For now, we'll simulate streaming
            by yielding the full response in chunks.
        """
        # For now, use non-streaming and simulate chunks
        # TODO: Implement true streaming with SSE
        response = await self.complete_async(prompt, system_prompt)
        full_response = response.content

        # Simulate streaming by yielding in chunks
        chunk_size = 20
        for i in range(0, len(full_response), chunk_size):
            chunk = full_response[i:i + chunk_size]
            yield chunk

    async def analyze_security_async(self, code_content: str, language: str) -> Dict[str, Any]:
        """
        Analyze code for security vulnerabilities using LLM.
        
        Args:
            code_content: Source code to analyze
            language: Language of the code
            
        Returns:
            Dict containing findings list
        """
        from warden.shared.utils.json_parser import parse_json_from_llm
        
        prompt = f"""
        You are a senior security researcher. Analyze this {language} code for critical vulnerabilities.
        Target vulnerabilities: SQL Injection, XSS, Hardcoded Secrets/Credentials, SSRF, CSRF, XXE, Insecure Deserialization, Path Traversal, and Command Injection.
        
        Ignore stylistic issues. Focus only on exploitable security flaws.
        
        Return a JSON object in this exact format:
        {{
            "findings": [
                {{
                    "severity": "critical|high|medium",
                    "message": "Short description",
                    "line_number": 1,
                    "detail": "Detailed explanation of the exploit vector"
                }}
            ]
        }}
        
        If no issues found, return {{ "findings": [] }}.
        
        Code:
        ```{language}
        {code_content[:4000]}
        ```
        """
        
        try:
            response = await self.complete_async(prompt, system_prompt="You are a strict security auditor. Output valid JSON only.")
            if not response.success:
                return {"findings": []}
                
            parsed = parse_json_from_llm(response.content)
            return parsed or {"findings": []}
        except (RuntimeError, ValueError, json.JSONDecodeError) as e:
            # Fallback to empty findings on failure to prevent crash
            from warden.shared.infrastructure.logging import get_logger
            logger = get_logger(__name__)
            logger.error("llm_security_analysis_failed", error=str(e))
            return {"findings": []}
