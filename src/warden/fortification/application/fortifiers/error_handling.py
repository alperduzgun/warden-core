"""
Error Handling Fortifier

Adds try-except blocks, error handling, and validation to code.
Detects risky operations (async, file I/O, network, database) and wraps them.
"""

import structlog
from dataclasses import dataclass
from typing import List, Optional

from warden.fortification.domain.base import BaseFortifier
from warden.fortification.domain.models import (
    FortificationResult,
    FortificationAction,
    FortificationActionType,
    FortifierPriority,
    Fortification,
)
from warden.validation.domain.frame import CodeFile
from warden.llm.factory import create_client

logger = structlog.get_logger()


@dataclass
class ErrorHandlingSuggestion:
    """Represents an error handling suggestion."""

    line_number: int
    type: str
    description: str
    severity: str = "High"


class ErrorHandlingFortifier(BaseFortifier):
    """
    Fortifier specialized in adding error handling (try-except blocks).

    Detects:
    - Async operations without error handling
    - File I/O operations
    - Network/HTTP requests
    - Database operations
    - External API calls
    """

    def __init__(self):
        """Initialize Error Handling Fortifier."""
        try:
            self._llm_provider = create_client()
        except Exception:
            self._llm_provider = None  # LLM optional

    @property
    def name(self) -> str:
        """Fortifier name."""
        return "Error Handling"

    @property
    def priority(self) -> FortifierPriority:
        """Execution priority."""
        return FortifierPriority.HIGH

    async def fortify_async(
        self,
        code_file: CodeFile,
        cancellation_token: Optional[str] = None,
    ) -> FortificationResult:
        """
        Fortify code by adding error handling.

        Args:
            code_file: The code file to fortify
            cancellation_token: Optional cancellation token

        Returns:
            FortificationResult with error handling added
        """
        if not code_file or not code_file.content:
            return FortificationResult(
                success=False,
                original_code="",
                fortified_code="",
                error_message="Code file is empty",
                fortifier_name=self.name,
            )

        # Analyze code for error handling needs
        suggestions = self._analyze_error_handling(code_file.content)

        if not suggestions:
            logger.info(
                "no_error_handling_issues",
                file_path=code_file.path,
                fortifier=self.name,
            )
            return FortificationResult(
                success=True,
                file_path=code_file.path,
                issues_found=0,
                suggestions=[],
                summary="No error handling issues found",
                fortifier_name=self.name,
            )

        logger.info(
            "error_handling_issues_found",
            count=len(suggestions),
            file_path=code_file.path,
        )

        # Create basic suggestions from static analysis
        fortification_suggestions = [
            Fortification(
                issue_line=s.line_number,
                issue_type=s.type,
                description=s.description,
                suggestion=f"Wrap this {s.type} in a try-except block to handle potential errors",
                severity=s.severity,
                code_snippet=self._get_code_snippet(code_file.content, s.line_number),
            )
            for s in suggestions
        ]

        # If LLM available, enhance suggestions
        if self._llm_provider is not None:
            logger.info(
                "enhancing_suggestions_with_llm",
                fortifier=self.name,
                file_path=code_file.path,
            )
            try:
                # Use LLM to generate better suggestions (NOT to modify code!)
                enhanced = await self._enhance_suggestions_with_llm(
                    code_file, fortification_suggestions
                )
                if enhanced:
                    fortification_suggestions = enhanced
            except Exception as e:
                logger.warning(
                    "llm_enhancement_failed",
                    error=str(e),
                    fortifier=self.name,
                )
                # Continue with basic suggestions

        return FortificationResult(
            success=True,
            file_path=code_file.path,
            issues_found=len(suggestions),
            suggestions=fortification_suggestions,
            summary=f"Found {len(suggestions)} error handling issues",
            fortifier_name=self.name,
        )

    def _analyze_error_handling(self, code: str) -> List[ErrorHandlingSuggestion]:
        """
        Analyze code for missing error handling.

        Args:
            code: Source code to analyze

        Returns:
            List of error handling suggestions
        """
        suggestions = []
        lines = code.split("\n")

        for i, line in enumerate(lines):
            stripped_line = line.strip()
            line_number = i + 1

            # Detect async/await without try-except
            if ("await " in stripped_line or "async def" in stripped_line) and not self._is_inside_try_except(
                lines, i
            ):
                suggestions.append(
                    ErrorHandlingSuggestion(
                        line_number=line_number,
                        type="AsyncOperation",
                        description="Async operation should be wrapped in try-except",
                        severity="High",
                    )
                )

            # Detect file operations
            if any(
                keyword in stripped_line
                for keyword in ["open(", "Path(", "os.path", "shutil."]
            ) and not self._is_inside_try_except(lines, i):
                suggestions.append(
                    ErrorHandlingSuggestion(
                        line_number=line_number,
                        type="FileOperation",
                        description="File operation should be wrapped in try-except",
                        severity="High",
                    )
                )

            # Detect HTTP/network requests
            if any(
                keyword in stripped_line
                for keyword in ["requests.", "httpx.", "urllib.", "aiohttp."]
            ) and not self._is_inside_try_except(lines, i):
                suggestions.append(
                    ErrorHandlingSuggestion(
                        line_number=line_number,
                        type="NetworkRequest",
                        description="Network request should be wrapped in try-except",
                        severity="Critical",
                    )
                )

            # Detect database operations
            if any(
                keyword in stripped_line
                for keyword in [".execute(", ".query(", "cursor.", "session."]
            ) and not self._is_inside_try_except(lines, i):
                suggestions.append(
                    ErrorHandlingSuggestion(
                        line_number=line_number,
                        type="DatabaseOperation",
                        description="Database operation should be wrapped in try-except",
                        severity="High",
                    )
                )

            # Detect JSON parsing
            if any(
                keyword in stripped_line
                for keyword in ["json.loads(", "json.load(", ".json()"]
            ) and not self._is_inside_try_except(lines, i):
                suggestions.append(
                    ErrorHandlingSuggestion(
                        line_number=line_number,
                        type="JsonParsing",
                        description="JSON parsing should be wrapped in try-except",
                        severity="Medium",
                    )
                )

        return suggestions

    @staticmethod
    def _is_inside_try_except(lines: List[str], line_index: int) -> bool:
        """
        Check if a line is inside a try-except block.

        Args:
            lines: All code lines
            line_index: Current line index

        Returns:
            True if inside try-except, False otherwise
        """
        indent_level = len(lines[line_index]) - len(lines[line_index].lstrip())

        # Scan backwards for try block
        for i in range(line_index - 1, -1, -1):
            current_line = lines[i].strip()
            current_indent = len(lines[i]) - len(lines[i].lstrip())

            # Found a try block at same or lower indent level
            if current_line.startswith("try:") and current_indent <= indent_level:
                return True

            # Stop if we're at a function/class definition
            if current_line.startswith("def ") or current_line.startswith("class "):
                break

        return False

    def _get_code_snippet(self, code: str, line_number: int, context: int = 2) -> str:
        """
        Extract code snippet around a specific line.

        Args:
            code: Full source code
            line_number: Target line number (1-indexed)
            context: Number of lines before/after to include

        Returns:
            Code snippet as string
        """
        lines = code.split("\n")
        start = max(0, line_number - context - 1)
        end = min(len(lines), line_number + context)

        snippet_lines = lines[start:end]
        return "\n".join(snippet_lines)

    async def _enhance_suggestions_with_llm(
        self,
        code_file: CodeFile,
        suggestions: List[Fortification],
    ) -> Optional[List[Fortification]]:
        """
        Use LLM to enhance suggestions with better descriptions.

        IMPORTANT: LLM provides suggestions, NOT code modifications!

        Args:
            code_file: Code file being analyzed
            suggestions: Basic suggestions from static analysis

        Returns:
            Enhanced suggestions with LLM-generated recommendations
        """
        if not suggestions:
            return suggestions

        # Build prompt for LLM (asking for suggestions, not code!)
        issues_list = "\n".join(
            f"- Line {s.issue_line}: {s.description}" for s in suggestions
        )

        prompt = f"""You are a code safety expert. For each issue below, provide a specific suggestion on how to fix it.

Code file: {code_file.path}

Issues found:
{issues_list}

For each issue, provide:
1. A clear explanation of why it's a problem
2. A specific suggestion on how to fix it (describe what to do, don't write code)

Format: JSON array of objects with keys: issueLine (int), suggestion (string)"""

        try:
            response = await self._llm_provider.complete_async(
                system_prompt="You are a code safety expert. Provide suggestions for fixing code issues. Never write code, only suggest what to do.",
                user_prompt=prompt,
                temperature=0.3,
                max_tokens=1000,
            )

            # Parse LLM response and enhance suggestions
            import json

            llm_suggestions = json.loads(response)

            # Match LLM suggestions with our suggestions
            llm_map = {s["issueLine"]: s["suggestion"] for s in llm_suggestions}

            enhanced = []
            for sug in suggestions:
                llm_text = llm_map.get(sug.issue_line, sug.suggestion)
                enhanced.append(
                    Fortification(
                        issue_line=sug.issue_line,
                        issue_type=sug.issue_type,
                        description=sug.description,
                        suggestion=llm_text,  # Enhanced by LLM
                        severity=sug.severity,
                        code_snippet=sug.code_snippet,
                    )
                )

            return enhanced

        except Exception as e:
            logger.warning(
                "llm_enhancement_parse_failed",
                error=str(e),
            )
            return suggestions  # Return original if LLM fails
