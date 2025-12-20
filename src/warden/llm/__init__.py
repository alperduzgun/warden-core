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
    LlmConfiguration,
    create_default_config,
    DEFAULT_MODELS
)

from .providers.base import ILlmClient
from .factory import LlmClientFactory

from .prompts import (
    ANALYSIS_SYSTEM_PROMPT,
    generate_analysis_request,
    CLASSIFICATION_SYSTEM_PROMPT,
    generate_classification_request
)

__all__ = [
    # Types
    "LlmProvider",
    "LlmRequest",
    "LlmResponse",
    "AnalysisIssue",
    "AnalysisResult",
    "ClassificationCharacteristics",
    "ClassificationResult",

    # Config
    "ProviderConfig",
    "LlmConfiguration",
    "create_default_config",
    "DEFAULT_MODELS",

    # Providers
    "ILlmClient",

    # Factory
    "LlmClientFactory",

    # Prompts
    "ANALYSIS_SYSTEM_PROMPT",
    "generate_analysis_request",
    "CLASSIFICATION_SYSTEM_PROMPT",
    "generate_classification_request",
]
