"""
LLM Integration Module

Multi-provider LLM support for Warden code analysis and classification

Based on C# implementation:
/Users/alper/vibe-code-analyzer/src/Warden.LLM/

Public API:
- LlmProvider: Provider enum
- LlmRequest/LlmResponse: Request/response types
- AnalysisResult/ClassificationResult: Analysis types
- LlmConfiguration: Configuration management
- ILlmClient: Provider interface
- LlmClientFactory: Client factory with fallback
- Prompts: Analysis and classification prompts
"""

from .config import LlmConfiguration, ProviderConfig, load_llm_config
from .factory import create_client, create_client_with_fallback_async, create_provider_client
from .prompts import (
    ANALYSIS_SYSTEM_PROMPT,
    CLASSIFICATION_SYSTEM_PROMPT,
    generate_analysis_request,
    generate_classification_request,
)
from .providers.base import ILlmClient
from .types import (
    AnalysisIssue,
    AnalysisResult,
    ClassificationCharacteristics,
    ClassificationResult,
    LlmProvider,
    LlmRequest,
    LlmResponse,
)

__all__ = [
    # Core factory functions
    "create_client",
    "create_provider_client",
    "create_client_with_fallback_async",
    # Types
    "LlmProvider",
    "LlmRequest",
    "LlmResponse",
    "AnalysisIssue",
    "AnalysisResult",
    "ClassificationCharacteristics",
    "ClassificationResult",
    "LlmConfiguration",
    "ProviderConfig",
    # Config
    "load_llm_config",
    # Providers
    "ILlmClient",
    # Prompts
    "ANALYSIS_SYSTEM_PROMPT",
    "generate_analysis_request",
    "CLASSIFICATION_SYSTEM_PROMPT",
    "generate_classification_request",
]
