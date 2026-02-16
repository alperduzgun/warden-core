"""
Offline LLM Provider
"""

from ..types import LlmProvider, LlmRequest, LlmResponse
from .base import ILlmClient


class OfflineClient(ILlmClient):
    """
    A no-op LLM client for Zombie Mode (Offline).
    """

    @property
    def provider(self) -> LlmProvider:
        return LlmProvider.UNKNOWN

    async def send_async(self, request: LlmRequest) -> LlmResponse:
        """
        Return a safe, empty response.
        """
        return LlmResponse(
            content="[Offline Mode] AI capabilities are disabled. Enable API keys for intelligence.",
            success=True,
            provider=self.provider,
            model="offline-fallback",
            token_usage={"prompt": 0, "completion": 0, "total": 0},
        )

    async def is_available_async(self) -> bool:
        """
        Always available (fallback).
        """
        return True

    async def complete_async(
        self, prompt: str, system_prompt: str = "", model: str | None = None, use_fast_tier: bool = False
    ) -> LlmResponse:
        return await self.send_async(None)

    async def analyze_security_async(self, code_content: str, language: str, use_fast_tier: bool = False) -> dict:
        """
        Return empty findings in offline mode.
        """
        return {"findings": []}
