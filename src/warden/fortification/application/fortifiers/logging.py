"""
Logging Fortifier

Adds structured logging (structlog) to functions and critical operations.
"""

import structlog
from dataclasses import dataclass
from typing import List, Optional

from warden.fortification.domain.base import BaseFortifier
from warden.fortification.domain.models import FortificationResult, FortifierPriority, FortificationAction, FortificationActionType
from warden.validation.domain.frame import CodeFile
from warden.llm.factory import create_client

logger = structlog.get_logger()


@dataclass
class LoggingSuggestion:
    """Represents a logging suggestion."""

    line_number: int
    type: str
    description: str
    severity: str = "Medium"


class LoggingFortifier(BaseFortifier):
    """
    Fortifier specialized in adding structured logging.

    Adds logging to:
    - Function entry/exit
    - Error handlers
    - Critical operations
    - External API calls
    - Database operations
    """

    def __init__(self):
        """Initialize Logging Fortifier."""
        try:
            self._llm_provider = create_client()
        except Exception:
            self._llm_provider = None  # LLM optional

    @property
    def name(self) -> str:
        """Fortifier name."""
        return "Logging"

    @property
    def priority(self) -> FortifierPriority:
        """Execution priority."""
        return FortifierPriority.MEDIUM

    async def fortify_async(
        self,
        code_file: CodeFile,
        cancellation_token: Optional[str] = None,
    ) -> FortificationResult:
        """
        Fortify code by adding structured logging.

        Args:
            code_file: The code file to fortify
            cancellation_token: Optional cancellation token

        Returns:
            FortificationResult with logging added
        """
        if not code_file or not code_file.content:
            return FortificationResult(
                success=False,
                original_code="",
                fortified_code="",
                error_message="Code file is empty",
                fortifier_name=self.name,
            )

        suggestions = self._analyze_logging(code_file.content)

        if not suggestions:
            logger.info(
                "no_logging_issues",
                file_path=code_file.path,
                fortifier=self.name,
            )
            return FortificationResult(
                success=True,
                original_code=code_file.content,
                fortified_code=code_file.content,
                summary="No logging improvements needed",
                fortifier_name=self.name,
            )

        logger.info(
            "logging_suggestions_found",
            count=len(suggestions),
            file_path=code_file.path,
        )

        prompt = self._build_logging_prompt(code_file, suggestions)

        try:
            response = await self._llm_provider.complete_async(
                system_prompt="You are a logging expert. Add structured logging (using structlog) to Python code. Return ONLY the modified code.",
                user_prompt=prompt,
                temperature=0.2,
                max_tokens=3000,
            )

            fortified_code = self._extract_code_from_markdown(
                response, code_file.content
            )

            actions = [
                FortificationAction(
                    type=FortificationActionType.LOGGING,
                    description=s.description,
                    line_number=s.line_number,
                    severity=s.severity,
                )
                for s in suggestions
            ]

            return FortificationResult(
                success=True,
                original_code=code_file.content,
                fortified_code=fortified_code,
                actions=actions,
                summary=f"Added logging at {len(suggestions)} locations",
                fortifier_name=self.name,
            )

        except Exception as e:
            logger.error(
                "fortification_failed",
                error=str(e),
                file_path=code_file.path,
                fortifier=self.name,
            )
            return FortificationResult(
                success=False,
                original_code=code_file.content,
                fortified_code=code_file.content,
                error_message=f"Fortification failed: {str(e)}",
                fortifier_name=self.name,
            )

    def _analyze_logging(self, code: str) -> List[LoggingSuggestion]:
        """Analyze code for missing logging."""
        suggestions = []
        lines = code.split("\n")

        for i, line in enumerate(lines):
            stripped_line = line.strip()
            line_number = i + 1

            # Detect function definitions without logging
            if stripped_line.startswith("def ") and not self._has_logging_nearby(
                lines, i
            ):
                suggestions.append(
                    LoggingSuggestion(
                        line_number=line_number,
                        type="FunctionEntry",
                        description="Function should have entry/exit logging",
                        severity="Medium",
                    )
                )

            # Detect except blocks without logging
            if stripped_line.startswith("except ") and not self._has_logging_in_block(
                lines, i
            ):
                suggestions.append(
                    LoggingSuggestion(
                        line_number=line_number,
                        type="ExceptionHandling",
                        description="Exception handler should log error",
                        severity="High",
                    )
                )

        return suggestions

    @staticmethod
    def _has_logging_nearby(lines: List[str], line_index: int, window: int = 5) -> bool:
        """Check if logging exists near a line."""
        start = max(0, line_index - window)
        end = min(len(lines), line_index + window)

        for i in range(start, end):
            if any(
                keyword in lines[i]
                for keyword in ["logger.", "logging.", "log."]
            ):
                return True

        return False

    @staticmethod
    def _has_logging_in_block(lines: List[str], start_index: int) -> bool:
        """Check if logging exists in except block."""
        indent_level = len(lines[start_index]) - len(lines[start_index].lstrip())

        for i in range(start_index + 1, len(lines)):
            current_indent = len(lines[i]) - len(lines[i].lstrip())

            if current_indent <= indent_level and lines[i].strip():
                break

            if any(
                keyword in lines[i]
                for keyword in ["logger.", "logging.", "log."]
            ):
                return True

        return False

    @staticmethod
    def _build_logging_prompt(
        code_file: CodeFile, suggestions: List[LoggingSuggestion]
    ) -> str:
        """Build LLM prompt for logging."""
        issues_list = "\n".join(
            f"- Line {s.line_number}: {s.description} ({s.type})"
            for s in suggestions
        )

        return f"""Add structured logging to this Python code:

Issues found:
{issues_list}

Code:
```python
{code_file.content}
```

Use structlog for logging. Add logger = structlog.get_logger() at the top.
Log function entry/exit, errors, and critical operations.
Return only the modified code."""
