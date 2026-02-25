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
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
        )

    async def is_available_async(self) -> bool:
        """
        Always available (fallback).
        """
        return True

    async def complete_async(
        self, prompt: str, system_prompt: str = "", model: str | None = None, use_fast_tier: bool = False
    ) -> LlmResponse:
        # Satisfy the LlmRequest type contract instead of passing None (#210)
        return await self.send_async(LlmRequest(system_prompt=system_prompt, user_message=prompt))

    async def analyze_security_async(self, code_content: str, language: str, use_fast_tier: bool = False) -> dict:
        """
        Return empty findings in offline mode.
        """
        return {"findings": []}
