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
        rate_limiter: Optional[Any] = None,
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
        self.rate_limiter = rate_limiter

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
            # Acquire rate limit if available
            if self.rate_limiter:
                # Estimate tokens: prompt chars / 4 + output estimate
                estimated_tokens = (len(prompt) // 4) + 1000
                await self.rate_limiter.acquire_async(estimated_tokens)

            # Determine model tier
            model = None
            if self.context and hasattr(self.context, 'llm_config') and self.context.llm_config:
                model = getattr(self.context.llm_config, 'fast_model', None)
            elif isinstance(self.context, dict) and "llm_config" in self.context:
                config = self.context["llm_config"]
                if isinstance(config, dict):
                    model = config.get("fast_model")
                else:
                    model = getattr(config, "fast_model", None)

            # Get LLM suggestions
            response = await self.llm_service.complete_async(
                prompt=prompt,
                system_prompt="You are a senior software engineer specialized in code quality and refactoring. Respond only with valid JSON.",
                model=model
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
        You are a **Senior Software Craftsman** and **Code Quality Architect**.
        Your goal is not just to find bugs, but to elevate the code to a state of **Elegance, Clarity, and Maintainability**.

        ### PHILOSOPHY
        1.  **Readability is King**: Code is read 10x more than it is written. Optimize for the reader's cognitive load.
        2.  **Behavioral Invariance**: You must NEVER change the functionality or external behavior of the code.
        3.  **Simplicity > Cleverness**: Prefer explicit, boring code over clever one-liners.
        4.  **Idiomatic Excellence**: Apply the highest standards of {language} best practices.

        ### PROJECT CONTEXT
        - Type: {project_type}
        - Framework: {framework}
        - Language: {language}
        - Quality Score: {self.context.get('quality_score_before', 0):.1f}/10

        ### TARGET CODE ({code_file.path}):
        ```{language}
        {code_snippet}
        ```

        ### ANALYSIS DIRECTIVES
        Identify specific opportunities to improve the code in these dimensions:

        1.  **Simplification**: Reduce nesting (Guard Clauses), simplify boolean logic, remove redundant variables.
        2.  **Modernization**: Use modern {language} features (e.g., f-strings, type hints, list comprehensions where appropriate).
        3.  **Cognitive Load**: Split complex functions, rename vague variables to precise intent.
        4.  **Structure**: Group related logic, enforce Separation of Concerns.
        5.  **Dead Code**: Ruthlessly identify unused elements.

        ### OUTPUT FORMAT
        Response MUST be valid JSON with this exact structure:

        {{
            "cleanings": [
                {{
                    "title": "Brief title (e.g., 'Use Guard Clause')",
                    "type": "simplification|modernization|dead_code|naming",
                    "location": "Line X or range",
                    "current_code": "The exact code block to change",
                    "improved_code": "The elegantly refactored version",
                    "impact": "low|medium|high",
                    "effort": "low|medium|high",
                    "description": "Why this improves the code (focus on maintainability)"
                }}
            ],
            "refactorings": [
                {{
                    "title": "Title for larger structural change",
                    "type": "complexity|structure",
                    "location": "Line range",
                    "current_code": "Snippet of the complex area",
                    "improved_code": "The refactored structure (or description if too large)",
                    "impact": "high",
                    "effort": "medium|high",
                    "description": "Architectural reasoning for this change"
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