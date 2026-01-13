"""
LLM Type Definitions - Panel Compatible

Multi-provider LLM support with fallback chain.
All types designed for Panel JSON compatibility (camelCase ↔ snake_case).
"""


from enum import Enum
from typing import Optional, List
from pydantic import Field
from warden.shared.domain.base_model import BaseDomainModel


class LlmProvider(str, Enum):
    """LLM provider types (matches C# LlmProvider enum)"""
    DEEPSEEK = "deepseek"
    QWENCODE = "qwencode"
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    AZURE_OPENAI = "azure_openai"
    GROQ = "groq"
    OPENROUTER = "openrouter"


class LlmRequest(BaseDomainModel):
    """Request to LLM provider"""
    system_prompt: str
    user_message: str
    model: Optional[str] = None
    temperature: float = 0.3
    max_tokens: int = 4000
    timeout_seconds: int = 60


class LlmResponse(BaseDomainModel):
    """Response from LLM provider"""
    content: str
    success: bool
    error_message: Optional[str] = None
    provider: Optional[LlmProvider] = None
    model: Optional[str] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    duration_ms: int = 0
    overall_confidence: Optional[float] = None


class AnalysisIssue(BaseDomainModel):
    """Single issue from LLM analysis"""
    severity: str
    category: str
    title: str
    description: str
    line: int
    confidence: float
    evidence_quote: str = Field(default="")
    code_snippet: str = Field(default="")
    suggestion: str = Field(default="")


class AnalysisResult(BaseDomainModel):
    """LLM analysis result"""
    score: float
    confidence: float
    summary: str
    scenarios_simulated: List[str] = Field(default_factory=list)
    issues: List[AnalysisIssue] = Field(default_factory=list)


class ClassificationCharacteristics(BaseDomainModel):
    """Code characteristics detected by classification"""
    has_async_operations: bool = False
    has_external_api_calls: bool = False
    has_user_input: bool = False
    has_database_operations: bool = False
    has_file_operations: bool = False
    has_financial_calculations: bool = False
    has_collection_processing: bool = False
    has_network_operations: bool = False
    has_authentication_logic: bool = False
    has_cryptographic_operations: bool = False
    complexity_score: int = 0


class ClassificationResult(BaseDomainModel):
    """LLM classification result"""
    characteristics: ClassificationCharacteristics
    recommended_frames: List[str]
    summary: str

