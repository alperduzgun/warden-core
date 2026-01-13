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

from .types import (
    LlmProvider,
    LlmRequest,
    LlmResponse,
    AnalysisIssue,
    AnalysisResult,
    ClassificationCharacteristics,
    ClassificationResult
)

from .config import (
    ProviderConfig,
    load_llm_config,
    LlmConfiguration
)

from .providers.base import ILlmClient
from .factory import create_client, create_provider_client, create_client_with_fallback

from .prompts import (
    ANALYSIS_SYSTEM_PROMPT,
    generate_analysis_request,
    CLASSIFICATION_SYSTEM_PROMPT,
    generate_classification_request
)

__all__ = [
    # Core factory functions
    "create_client",
    "create_provider_client",
    "create_client_with_fallback",

    # Types
    "LlmProvider",
    "LlmConfig",
    "LlmRequest",
    "LlmResponse",
    "ContextWindow",
    "TokenUsage",
    "AnalysisIssue",
    "AnalysisResult",
    "ClassificationCharacteristics",
    "ClassificationResult",
    "LlmConfiguration",

    # Config
    "load_llm_config",

    # Providers
    "ILlmClient",

    # Factory
    # "LlmClientFactory",  # Removed in favor of functional factory

    # Prompts
    "ANALYSIS_SYSTEM_PROMPT",
    "generate_analysis_request",
    "CLASSIFICATION_SYSTEM_PROMPT",
    "generate_classification_request",
]
