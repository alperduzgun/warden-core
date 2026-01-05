"""
LLM-Based Cleaning Suggestion Generator.

Generates intelligent code quality improvement suggestions using language models.
"""

import json
import re
from typing import Any, Dict, List, Optional

from warden.validation.domain.frame import CodeFile
from warden.shared.infrastructure.logging import get_logger

# Try to import LLMService, use None if not available
try:
    from warden.shared.services import LLMService
except ImportError:
    LLMService = None

logger = get_logger(__name__)


class LLMSuggestionGenerator:
    """
    Generates code improvement suggestions using LLM.

    Responsibilities:
    - Create context-aware prompts
    - Parse LLM responses
    - Generate cleaning and refactoring suggestions
    """

    def __init__(
        self,
        llm_service: LLMService,
        context: Optional[Dict[str, Any]] = None,
        semantic_search_service: Optional[Any] = None,
    ):
        """
        Initialize LLM suggestion generator.

        Args:
            llm_service: LLM service for generating suggestions
            context: Pipeline context with project information
            semantic_search_service: Optional semantic search service
        """
        self.llm_service = llm_service
        self.context = context or {}
        self.semantic_search_service = semantic_search_service

        logger.info(
            "llm_suggestion_generator_initialized",
            has_context=bool(context),
        )

    async def generate_suggestions_async(
        self,
        code_file: CodeFile,
    ) -> Dict[str, Any]:
        """
        Generate cleaning suggestions using LLM.

        Args:
            code_file: Code file to analyze

        Returns:
            Dictionary with cleanings and refactorings
        """
        # Get semantic context
        semantic_context = ""
        if self.semantic_search_service and self.semantic_search_service.is_available():
            try:
                search_results = await self.semantic_search_service.search(
                    query=f"Code patterns and utilities used in {code_file.path}",
                    limit=3
                )
                if search_results:
                    semantic_context = "\n[Global Code Patterns]:\n"
                    for res in search_results:
                        if res.file_path != code_file.path:
                            semantic_context += f"- In {res.file_path}: {res.content[:150]}...\n"
            except Exception as e:
                logger.warning("cleaning_semantic_search_failed", file=code_file.path, error=str(e))

        # Create context-aware prompt
        prompt = self.create_prompt(code_file)
        if semantic_context:
            prompt += f"\n# ADDITIONAL CONTEXT\n{semantic_context}"

        try:
            # Get LLM suggestions
            response = await self.llm_service.complete_async(
                prompt=prompt,
                system_prompt="You are a senior software engineer specialized in code quality and refactoring. Respond only with valid JSON.",
            )

            # Parse LLM response - response is an LlmResponse object
            response_text = response.content if hasattr(response, 'content') else str(response)
            suggestions = self.parse_response(response_text, code_file)

            logger.info(
                "llm_suggestions_generated",
                file=code_file.path,
                cleanings=len(suggestions.get("cleanings", [])),
                refactorings=len(suggestions.get("refactorings", [])),
            )

            return suggestions

        except Exception as e:
            logger.error(
                "llm_suggestion_generation_failed",
                file=code_file.path,
                error=str(e),
            )
            # Return empty suggestions on failure
            return {"cleanings": [], "refactorings": []}

    def create_prompt(
        self,
        code_file: CodeFile,
    ) -> str:
        """
        Create LLM prompt for cleaning suggestions.

        Args:
            code_file: Code file to analyze

        Returns:
            Formatted prompt for LLM
        """
        # Get context information
        project_type = self.context.get("project_type", "unknown")
        framework = self.context.get("framework", "unknown")
        language = self.context.get("language", "python")

        # Include relevant findings from validation
        findings = self.context.get("findings", [])
        
        def get_file_path(f):
            if isinstance(f, dict):
                return f.get("file_path")
            return getattr(f, "path", getattr(f, "file_path", None))
            
        file_findings = [f for f in findings if get_file_path(f) == code_file.path]

        # Truncate code for prompt (first 3000 chars)
        code_snippet = code_file.content[:3000]

        prompt = f"""
        You are a senior software engineer reviewing code for quality improvements.

        PROJECT CONTEXT:
        - Type: {project_type}
        - Framework: {framework}
        - Language: {language}
        - Current Quality Score: {self.context.get('quality_score_before', 0):.1f}/10

        FILE: {code_file.path}

        CODE TO REVIEW:
        ```{language}
        {code_snippet}
        ```

        KNOWN ISSUES ({len(file_findings)} security issues found):
        {self._format_findings(file_findings[:5])}

        Analyze this code and suggest improvements in these areas:

        1. DEAD CODE: Identify unused imports, variables, functions
        2. DUPLICATION: Find repeated code that could be extracted
        3. COMPLEXITY: Identify overly complex functions needing refactoring
        4. NAMING: Suggest better names for variables and functions
        5. STRUCTURE: Recommend better code organization
        6. PERFORMANCE: Identify optimization opportunities
        7. BEST PRACTICES: Suggest {framework} best practices

        Format your response as JSON with two arrays:
        - cleanings: Simple improvements (dead code, naming, imports)
        - refactorings: Complex changes (extract methods, restructure)

        Each suggestion should have:
        - title: Brief description
        - type: Category of improvement
        - location: Where in the code
        - current_code: The problematic code
        - improved_code: The suggested improvement
        - impact: Expected impact on quality (low/medium/high)
        - effort: Implementation effort (low/medium/high)

        Example response:
        {{
            "cleanings": [
                {{
                    "title": "Remove unused import",
                    "type": "dead_code",
                    "location": "Line 5",
                    "current_code": "import unused_module",
                    "improved_code": "",
                    "impact": "low",
                    "effort": "low"
                }}
            ],
            "refactorings": [
                {{
                    "title": "Extract complex validation logic",
                    "type": "complexity",
                    "location": "Lines 50-120",
                    "current_code": "# Complex function body",
                    "improved_code": "# Refactored into smaller functions",
                    "impact": "high",
                    "effort": "medium"
                }}
            ]
        }}
        """

        return prompt

    def parse_response(
        self,
        response: str,
        code_file: CodeFile,
    ) -> Dict[str, Any]:
        """
        Parse LLM response into cleaning suggestions.

        Args:
            response: LLM response text
            code_file: Original code file

        Returns:
            Dictionary with parsed suggestions
        """
        cleanings = []
        refactorings = []

        try:
            # Extract JSON from response
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())

                # Process cleanings
                cleanings = self._parse_suggestions(
                    data.get("cleanings", []),
                    code_file.path,
                    "cleaning",
                )

                # Process refactorings
                refactorings = self._parse_suggestions(
                    data.get("refactorings", []),
                    code_file.path,
                    "refactoring",
                )

                logger.info(
                    "llm_response_parsed",
                    cleanings_count=len(cleanings),
                    refactorings_count=len(refactorings),
                )

        except (json.JSONDecodeError, AttributeError) as e:
            logger.error(
                "llm_response_parsing_failed",
                error=str(e),
                response_preview=response[:200],
            )

            # Create fallback suggestion if parsing fails
            cleanings.append(self._create_fallback_suggestion(code_file.path, response))

        return {
            "cleanings": cleanings,
            "refactorings": refactorings,
        }

    def _parse_suggestions(
        self,
        suggestion_list: List[Dict],
        file_path: str,
        suggestion_category: str,
    ) -> List[Dict[str, Any]]:
        """
        Parse and validate suggestion list.

        Args:
            suggestion_list: Raw suggestions from LLM
            file_path: Path to the file
            suggestion_category: 'cleaning' or 'refactoring'

        Returns:
            List of validated suggestions
        """
        parsed_suggestions = []

        for item in suggestion_list:
            try:
                suggestion = {
                    "title": item.get("title", f"Code {suggestion_category}"),
                    "type": item.get("type", "general"),
                    "file_path": file_path,
                    "location": item.get("location", ""),
                    "current_code": item.get("current_code", ""),
                    "improved_code": item.get("improved_code", ""),
                    "impact": self._validate_impact(item.get("impact")),
                    "effort": self._validate_effort(item.get("effort")),
                    "confidence": 0.85,
                    "generated_by": "llm",
                }

                # Add additional metadata
                if "description" in item:
                    suggestion["description"] = item["description"]

                if "recommendation" in item:
                    suggestion["recommendation"] = item["recommendation"]

                parsed_suggestions.append(suggestion)

            except Exception as e:
                logger.warning(
                    "suggestion_parsing_error",
                    error=str(e),
                    suggestion_category=suggestion_category,
                )

        return parsed_suggestions

    def _validate_impact(
        self,
        impact: Optional[str],
    ) -> str:
        """
        Validate and normalize impact level.

        Args:
            impact: Raw impact value

        Returns:
            Normalized impact level
        """
        valid_impacts = ["low", "medium", "high"]
        if impact and impact.lower() in valid_impacts:
            return impact.lower()
        return "medium"

    def _validate_effort(
        self,
        effort: Optional[str],
    ) -> str:
        """
        Validate and normalize effort level.

        Args:
            effort: Raw effort value

        Returns:
            Normalized effort level
        """
        valid_efforts = ["low", "medium", "high"]
        if effort and effort.lower() in valid_efforts:
            return effort.lower()
        return "medium"

    def _create_fallback_suggestion(
        self,
        file_path: str,
        response: str,
    ) -> Dict[str, Any]:
        """
        Create a fallback suggestion when parsing fails.

        Args:
            file_path: Path to the file
            response: Original LLM response

        Returns:
            Basic suggestion dictionary
        """
        return {
            "title": "Code Quality Review Needed",
            "type": "general",
            "file_path": file_path,
            "description": response[:500] if response else "Manual review recommended",
            "impact": "medium",
            "effort": "medium",
            "confidence": 0.5,
            "generated_by": "fallback",
        }

    def _format_findings(
        self,
        findings: List[Dict[str, Any]],
    ) -> str:
        """
        Format security findings for prompt.

        Args:
            findings: List of security findings

        Returns:
            Formatted string for prompt
        """
        if not findings:
            return "No security issues in this file"

        formatted = []
        for finding in findings:
            # Handle both dict and object access
            if isinstance(finding, dict):
                finding_type = finding.get('type', 'issue')
                message = finding.get('message', 'Security issue')
                line = finding.get('line_number', 'unknown')
            else:
                finding_type = getattr(finding, 'type', 'issue')
                message = getattr(finding, 'message', 'Security issue')
                line = getattr(finding, 'line_number', 'unknown')
            
            formatted.append(f"- {finding_type}: {message} (line {line})")

        return "\n".join(formatted)

    async def generate_batch_suggestions_async(
        self,
        code_files: List[CodeFile],
        batch_size: int = 5,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Generate suggestions for multiple files in batches.

        Args:
            code_files: List of code files
            batch_size: Number of files per batch

        Returns:
            Dictionary mapping file paths to suggestions
        """
        all_suggestions = {}

        # Process files in batches
        for i in range(0, len(code_files), batch_size):
            batch = code_files[i:i + batch_size]

            # Generate suggestions for each file in parallel
            import asyncio
            tasks = [
                self.generate_suggestions_async(code_file)
                for code_file in batch
            ]

            batch_results = await asyncio.gather(*tasks, return_exceptions=True)

            # Map results to file paths
            for code_file, result in zip(batch, batch_results):
                if isinstance(result, Exception):
                    logger.error(
                        "batch_suggestion_error",
                        file=code_file.path,
                        error=str(result),
                    )
                    all_suggestions[code_file.path] = {
                        "cleanings": [],
                        "refactorings": [],
                    }
                else:
                    all_suggestions[code_file.path] = result

        logger.info(
            "batch_suggestions_completed",
            files_processed=len(code_files),
            batch_size=batch_size,
        )

        return all_suggestions