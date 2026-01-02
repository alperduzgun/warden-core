"""
Shared services module for cross-cutting concerns.

Provides common services used across different phases:
- LLM service for AI-powered analysis
- Code formatting service
- Security suggestion service
"""

from typing import Optional, List, Dict, Any
import asyncio

from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)


class LLMService:
    """Service for LLM-based analysis and suggestions."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize LLM service."""
        self.config = config or {}
        self.enabled = self.config.get("enabled", False)

        # Try to import LLM client
        try:
            from warden.llm.config import load_llm_config
            from warden.llm.factory import create_client
            
            llm_config = load_llm_config()
            self.llm_service = create_client(llm_config.default_provider)
            self.llm_available = True
            logger.info("llm_service_initialized", enabled=self.enabled)
        except Exception as e:
            self.llm_available = False
            logger.warning("llm_service_unavailable", error=str(e))

    async def generate_suggestion(self, issue: Dict[str, Any]) -> Optional[str]:
        """Generate a fix suggestion for an issue."""
        if not self.enabled or not self.llm_available:
            return None

        try:
            prompt = self._build_suggestion_prompt(issue)
            # Simplified for now
            return f"Fix suggestion for {issue.get('message', 'issue')}"
        except Exception as e:
            logger.error("suggestion_generation_failed", error=str(e))
            return None

    async def analyze_code(self, code: str, context: str = "") -> Dict[str, Any]:
        """Analyze code with LLM."""
        if not self.enabled or not self.llm_available:
            return {"analysis": "LLM not available"}

        try:
            # Simplified for now
            return {
                "analysis": "Code analysis result",
                "suggestions": [],
                "confidence": 0.5
            }
        except Exception as e:
            logger.error("code_analysis_failed", error=str(e))
            return {"error": str(e)}

    def _build_suggestion_prompt(self, issue: Dict[str, Any]) -> str:
        """Build prompt for suggestion generation."""
        return f"""
        Issue: {issue.get('message', '')}
        Severity: {issue.get('severity', 'medium')}
        File: {issue.get('file_path', '')}
        Line: {issue.get('line', 0)}

        Please provide a fix suggestion.
        """


class SecuritySuggestionService:
    """Service for generating security fix suggestions."""

    def __init__(self, llm_service: Optional[LLMService] = None):
        """Initialize security suggestion service."""
        self.llm_service = llm_service or LLMService()

    async def generate_fortification(self, issue: Dict[str, Any]) -> Dict[str, Any]:
        """Generate fortification for a security issue."""
        severity = issue.get("severity", "medium")

        # Base fortification
        fortification = {
            "issue_id": issue.get("id"),
            "type": issue.get("type", "security"),
            "severity": severity,
            "auto_fixable": False,
            "suggestion": None,
            "confidence": 0.0
        }

        # Generate suggestion based on issue type
        issue_type = issue.get("code", "unknown")

        if issue_type == "sql_injection":
            fortification["suggestion"] = "Use parameterized queries instead of string interpolation"
            fortification["auto_fixable"] = True
            fortification["confidence"] = 0.9
        elif issue_type == "hardcoded_password":
            fortification["suggestion"] = "Use environment variables for sensitive data"
            fortification["auto_fixable"] = True
            fortification["confidence"] = 0.95
        elif issue_type == "xss":
            fortification["suggestion"] = "Sanitize user input and escape output"
            fortification["confidence"] = 0.85
        else:
            # Try to get LLM suggestion
            if self.llm_service:
                suggestion = await self.llm_service.generate_suggestion(issue)
                if suggestion:
                    fortification["suggestion"] = suggestion
                    fortification["confidence"] = 0.7

        return fortification


class CodeImprovementService:
    """Service for generating code quality improvements."""

    def __init__(self, llm_service: Optional[LLMService] = None):
        """Initialize code improvement service."""
        self.llm_service = llm_service or LLMService()

    async def generate_cleaning_suggestion(
        self,
        code: str,
        issues: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Generate cleaning suggestions for code."""

        suggestions = []

        # Analyze issues to determine improvements
        for issue in issues:
            issue_type = issue.get("type", "")

            if "complexity" in issue_type:
                suggestions.append({
                    "type": "refactor",
                    "target": issue.get("function", ""),
                    "suggestion": "Break down complex function into smaller ones",
                    "priority": "medium"
                })
            elif "duplication" in issue_type:
                suggestions.append({
                    "type": "extract",
                    "target": issue.get("code_block", ""),
                    "suggestion": "Extract duplicated code into a shared function",
                    "priority": "high"
                })
            elif "naming" in issue_type:
                suggestions.append({
                    "type": "rename",
                    "target": issue.get("identifier", ""),
                    "suggestion": "Use more descriptive names",
                    "priority": "low"
                })

        return {
            "cleaning_suggestions": suggestions,
            "refactorings": [],
            "quality_score_after": 0.0,
            "code_improvements": []
        }


# Export services
__all__ = [
    "LLMService",
    "SecuritySuggestionService",
    "CodeImprovementService",
]