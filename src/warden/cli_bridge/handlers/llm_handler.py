"""
LLM Handler for Warden Bridge.
Handles AI-driven code analysis and streaming responses.
"""

from typing import Any, Dict, List, Optional, AsyncIterator
from warden.shared.infrastructure.logging import get_logger
from warden.cli_bridge.protocol import IPCError, ErrorCode
from warden.cli_bridge.handlers.base import BaseHandler

logger = get_logger(__name__)

class LLMHandler(BaseHandler):
    """Handles LLM-powered analysis and chat streaming."""

    def __init__(self, llm_config: Any):
        self.llm_config = llm_config

    async def analyze_with_llm(self, prompt: str, provider: Optional[str] = None, stream: bool = True) -> AsyncIterator[str]:
        """Execute LLM analysis with streaming or full completion."""
        from warden.llm.types import LlmProvider
        from warden.llm.factory import create_client
        
        try:
            # Resolve provider
            resolved_provider = self.llm_config.default_provider
            if provider:
                try:
                    resolved_provider = LlmProvider(provider)
                except ValueError:
                    raise IPCError(ErrorCode.INVALID_PARAMS, f"Invalid provider: {provider}")

            # Get client
            llm_client = create_client(resolved_provider)
            if not llm_client:
                raise IPCError(ErrorCode.LLM_ERROR, "No LLM provider available")

            if stream:
                async for chunk in llm_client.stream_completion(prompt):
                    yield chunk
            else:
                response = await llm_client.complete_async(prompt)
                yield response.content

        except IPCError:
            raise
        except Exception as e:
            logger.error("llm_analysis_failed", error=str(e), provider=provider)
            raise IPCError(ErrorCode.LLM_ERROR, f"LLM analysis failed: {e}")
