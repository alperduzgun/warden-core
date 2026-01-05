"""
Base LLM Client Interface

Based on C# ILlmClient.cs:
/Users/alper/vibe-code-analyzer/src/Warden.LLM/ILlmClient.cs

All provider implementations must inherit from this interface
"""

from abc import ABC, abstractmethod
import json
from ..types import LlmProvider, LlmRequest, LlmResponse


class ILlmClient(ABC):
    """
    Interface for LLM providers

    Matches C# ILlmClient interface
    All providers (Anthropic, DeepSeek, QwenCode, etc.) must implement this
    """

    @property
    @abstractmethod
    def provider(self) -> LlmProvider:
        """
        The provider type

        Returns:
            LlmProvider enum value
        """
        pass

    @abstractmethod
    async def send_async(self, request: LlmRequest) -> LlmResponse:
        """
        Send a request to the LLM provider

        Args:
            request: The LLM request parameters

        Returns:
            LLM response with content or error

        Raises:
            Should NOT raise exceptions - return LlmResponse with success=False instead
        """
        pass

    @abstractmethod
    async def is_available_async(self) -> bool:
        """
        Check if the provider is available/configured

        Returns:
            True if the provider is ready to use, False otherwise

        Note:
            Should NOT raise exceptions - return False on any error
        """
        pass

    async def complete_async(self, prompt: str, system_prompt: str = "You are a helpful coding assistant.") -> LlmResponse:
        """
        Simple completion method for non-streaming requests.

        Args:
            prompt: User prompt
            system_prompt: System prompt (optional)

        Returns:
            LlmResponse with content and token usage

        Raises:
            Exception: If request fails
        """
        # Default implementation using send_async
        request = LlmRequest(
            user_message=prompt,
            system_prompt=system_prompt,
            model=None,  # Use provider default
            temperature=0.7,
            max_tokens=2000,
            timeout_seconds=30.0
        )

        response = await self.send_async(request)

        if not response.success:
            raise Exception(f"LLM request failed: {response.error_message}")

        return response

    async def analyze_security_async(self, code_content: str, language: str) -> dict:
        """
        Analyze code for security vulnerabilities using LLM.
        
        Default implementation uses complete_async with a standard prompt.
        Providers may override this for specialized models or parameters.
        
        Args:
            code_content: Source code to analyze
            language: Language of the code
            
        Returns:
            Dict containing findings list
        """
        from warden.shared.utils.json_parser import parse_json_from_llm
        from typing import Dict, Any

        prompt = f"""
        You are a senior security researcher. Analyze this {language} code for critical vulnerabilities.
        Target vulnerabilities: SSRF, CSRF, XXE, Insecure Deserialization, Path Traversal, and Command Injection.
        
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
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            # Log but don't crash - return safe default
            return {"findings": []}
