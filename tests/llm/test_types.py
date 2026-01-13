"""Test LLM types and Panel JSON compatibility"""

import pytest
from warden.llm.types import (
    LlmProvider,
    LlmRequest,
    LlmResponse,
    AnalysisIssue,
    AnalysisResult,
)


def test_llm_provider_enum():
    """Test LlmProvider enum values"""
    assert LlmProvider.ANTHROPIC.value == "anthropic"
    assert LlmProvider.DEEPSEEK.value == "deepseek"
    assert LlmProvider.QWENCODE.value == "qwencode"
    assert LlmProvider.OPENAI.value == "openai"
    assert LlmProvider.GROQ.value == "groq"


def test_llm_request_defaults():
    """Test LlmRequest default values"""
    request = LlmRequest(
        system_prompt="Test system",
        user_message="Test message"
    )

    assert request.temperature == 0.3
    assert request.max_tokens == 4000
    assert request.timeout_seconds == 60


def test_llm_response_to_dict():
    """Test LlmResponse Panel JSON compatibility (camelCase)"""
    response = LlmResponse(
        content="Test content",
        success=True,
        provider=LlmProvider.ANTHROPIC,
        model="claude-3-5-sonnet",
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150,
        duration_ms=1000,
        overall_confidence=0.95
    )

    result = response.to_dict()

    # Check camelCase keys (Panel compatibility)
    assert "content" in result
    assert "success" in result
    assert "errorMessage" in result  # camelCase!
    assert "provider" in result
    assert "promptTokens" in result  # camelCase!
    assert "completionTokens" in result  # camelCase!
    assert "totalTokens" in result  # camelCase!
    assert "durationMs" in result  # camelCase!
    assert "overallConfidence" in result  # camelCase!

    assert result["provider"] == "anthropic"
    assert result["promptTokens"] == 100


def test_analysis_issue_to_dict():
    """Test AnalysisIssue Panel JSON compatibility"""
    issue = AnalysisIssue(
        severity="critical",
        category="security",
        title="SQL Injection",
        description="Direct SQL concatenation",
        line=45,
        confidence=0.95,
        evidence_quote='query = f"SELECT * FROM users WHERE id = {user_id}"',
        code_snippet='query = f"SELECT * FROM users WHERE id = {user_id}"'
    )

    result = issue.to_dict()

    # Check camelCase
    assert "evidenceQuote" in result  # camelCase!
    assert "codeSnippet" in result  # camelCase!
    assert result["confidence"] == 0.95


def test_analysis_issue_from_dict():
    """Test parsing AnalysisIssue from LLM JSON response"""
    data = {
        "severity": "high",
        "category": "reliability",
        "title": "Missing error handling",
        "description": "No try-except block",
        "line": 10,
        "confidence": 0.85,
        "evidenceQuote": "await api_call()",
        "codeSnippet": "await api_call()"
    }

    issue = AnalysisIssue.from_dict(data)

    assert issue.severity == "high"
    assert issue.confidence == 0.85
    assert issue.evidence_quote == "await api_call()"


def test_analysis_result_to_dict():
    """Test AnalysisResult Panel compatibility"""
    issue = AnalysisIssue(
        severity="medium",
        category="code_quality",
        title="Long function",
        description="Function exceeds 50 lines",
        line=100,
        confidence=0.9,
        evidence_quote="def long_function():",
        code_snippet="def long_function():"
    )

    result = AnalysisResult(
        score=6.5,
        confidence=0.8,
        summary="Code needs refactoring",
        issues=[issue]
    )

    data = result.to_dict()

    assert data["score"] == 6.5
    assert data["confidence"] == 0.8
    assert len(data["issues"]) == 1
    assert "evidenceQuote" in data["issues"][0]


def test_analysis_result_from_dict():
    """Test parsing AnalysisResult from LLM response"""
    data = {
        "score": 7.5,
        "confidence": 0.85,
        "summary": "Good code quality",
        "issues": [
            {
                "severity": "low",
                "category": "performance",
                "title": "Inefficient loop",
                "description": "Use list comprehension",
                "line": 20,
                "confidence": 0.7,
                "evidenceQuote": "for x in range(10):",
                "codeSnippet": "for x in range(10):"
            }
        ]
    }

    result = AnalysisResult.from_dict(data)

    assert result.score == 7.5
    assert len(result.issues) == 1
    assert result.issues[0].severity == "low"
