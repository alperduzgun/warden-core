"""
Base LLM Client Interface

Based on C# ILlmClient.cs:
/Users/alper/vibe-code-analyzer/src/Warden.LLM/ILlmClient.cs

All provider implementations must inherit from this interface
"""

from abc import ABC, abstractmethod
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
