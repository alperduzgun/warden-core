"""
LLM Type Definitions - Panel Compatible

Based on:
- C#: /Users/alper/vibe-code-analyzer/src/Warden.LLM/
- Panel: /Users/alper/Documents/Development/warden-panel/src/lib/types/warden.ts

All types designed for Panel JSON compatibility (camelCase ↔ snake_case)
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Optional


class LlmProvider(str, Enum):
    """LLM provider types (matches C# LlmProvider enum)"""
    DEEPSEEK = "deepseek"
    QWENCODE = "qwencode"
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    AZURE_OPENAI = "azure_openai"
    GROQ = "groq"
    OPENROUTER = "openrouter"


@dataclass
class LlmRequest:
    """
    Request to LLM provider

    Matches C# LlmRequest.cs
    """
    system_prompt: str
    user_message: str
    model: Optional[str] = None
    temperature: float = 0.3  # Low temperature for code analysis
    max_tokens: int = 4000
    timeout_seconds: int = 60


@dataclass
class LlmResponse:
    """
    Response from LLM provider

    Matches C# LlmResponse.cs + Panel compatibility
    """
    content: str
    success: bool
    error_message: Optional[str] = None
    provider: Optional[LlmProvider] = None
    model: Optional[str] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    duration_ms: int = 0
    overall_confidence: Optional[float] = None  # 0.0-1.0

    def to_dict(self) -> dict:
        """Convert to camelCase for Panel JSON compatibility"""
        return {
            "content": self.content,
            "success": self.success,
            "errorMessage": self.error_message,
            "provider": self.provider.value if self.provider else None,
            "model": self.model,
            "promptTokens": self.prompt_tokens,
            "completionTokens": self.completion_tokens,
            "totalTokens": self.total_tokens,
            "durationMs": self.duration_ms,
            "overallConfidence": self.overall_confidence
        }


@dataclass
class AnalysisIssue:
    """
    Single issue from LLM analysis

    Panel compatible - matches WardenIssue structure from Panel
    """
    severity: str  # "critical", "high", "medium", "low"
    category: str  # "security", "reliability", "resource_management", etc.
    title: str
    description: str
    line: int
    confidence: float  # 0.0-1.0 (NEW: accuracy first!)
    evidence_quote: str  # EXACT code from file (NEW: no evidence = no issue)
    code_snippet: str

    def to_dict(self) -> dict:
        """Convert to camelCase for Panel"""
        return {
            "severity": self.severity,
            "category": self.category,
            "title": self.title,
            "description": self.description,
            "line": self.line,
            "confidence": self.confidence,
            "evidenceQuote": self.evidence_quote,  # camelCase
            "codeSnippet": self.code_snippet  # camelCase
        }

    @staticmethod
    def from_dict(data: dict) -> "AnalysisIssue":
        """Parse from LLM JSON response"""
        return AnalysisIssue(
            severity=data["severity"],
            category=data["category"],
            title=data["title"],
            description=data["description"],
            line=data["line"],
            confidence=data["confidence"],
            evidence_quote=data.get("evidenceQuote", ""),
            code_snippet=data.get("codeSnippet", "")
        )


@dataclass
class AnalysisResult:
    """
    LLM analysis result

    Matches expected JSON response format from prompts
    """
    score: float  # 0-10
    confidence: float  # 0.0-1.0 overall confidence
    summary: str
    issues: list[AnalysisIssue] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to camelCase for Panel"""
        return {
            "score": self.score,
            "confidence": self.confidence,
            "summary": self.summary,
            "issues": [issue.to_dict() for issue in self.issues]
        }

    @staticmethod
    def from_dict(data: dict) -> "AnalysisResult":
        """Parse from LLM JSON response"""
        return AnalysisResult(
            score=data["score"],
            confidence=data["confidence"],
            summary=data["summary"],
            issues=[AnalysisIssue.from_dict(issue) for issue in data.get("issues", [])]
        )


@dataclass
class ClassificationCharacteristics:
    """
    Code characteristics detected by classification

    Matches C# ClassificationPrompt detection logic
    """
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
    complexity_score: int = 0  # 1-10


@dataclass
class ClassificationResult:
    """
    LLM classification result

    Recommends which validation frames to apply
    """
    characteristics: ClassificationCharacteristics
    recommended_frames: list[str]  # ["Security", "Chaos", "Fuzz", etc.]
    summary: str

    def to_dict(self) -> dict:
        """Convert to Panel-compatible format"""
        return {
            "characteristics": {
                "hasAsyncOperations": self.characteristics.has_async_operations,
                "hasExternalApiCalls": self.characteristics.has_external_api_calls,
                "hasUserInput": self.characteristics.has_user_input,
                "hasDatabaseOperations": self.characteristics.has_database_operations,
                "hasFileOperations": self.characteristics.has_file_operations,
                "hasFinancialCalculations": self.characteristics.has_financial_calculations,
                "hasCollectionProcessing": self.characteristics.has_collection_processing,
                "hasNetworkOperations": self.characteristics.has_network_operations,
                "hasAuthenticationLogic": self.characteristics.has_authentication_logic,
                "hasCryptographicOperations": self.characteristics.has_cryptographic_operations,
                "complexityScore": self.characteristics.complexity_score
            },
            "recommendedFrames": self.recommended_frames,
            "summary": self.summary
        }
