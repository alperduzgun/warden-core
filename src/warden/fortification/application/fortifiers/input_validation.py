"""
Input Validation Fortifier

Adds input validation checks to function parameters.
Prevents malicious/invalid inputs from causing issues.
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
class ValidationSuggestion:
    """Represents an input validation suggestion."""

    line_number: int
    parameter_name: str
    description: str
    severity: str = "High"


class InputValidationFortifier(BaseFortifier):
    """
    Fortifier specialized in adding input validation.

    Adds validation for:
    - Function parameters
    - User inputs
    - File paths (path traversal prevention)
    - SQL parameters (injection prevention)
    - JSON data
    """

    def __init__(self):
        """Initialize Input Validation Fortifier."""
        try:
            self._llm_provider = create_client()
        except Exception:
            self._llm_provider = None  # LLM optional

    @property
    def name(self) -> str:
        """Fortifier name."""
        return "Input Validation"

    @property
    def priority(self) -> FortifierPriority:
        """Execution priority."""
        return FortifierPriority.CRITICAL

    async def fortify_async(
        self,
        code_file: CodeFile,
        cancellation_token: Optional[str] = None,
    ) -> FortificationResult:
        """
        Fortify code by adding input validation.

        Args:
            code_file: The code file to fortify
            cancellation_token: Optional cancellation token

        Returns:
            FortificationResult with validation added
        """
        if not code_file or not code_file.content:
            return FortificationResult(
                success=False,
                original_code="",
                fortified_code="",
                error_message="Code file is empty",
                fortifier_name=self.name,
            )

        suggestions = self._analyze_validation(code_file.content)

        if not suggestions:
            return FortificationResult(
                success=True,
                original_code=code_file.content,
                fortified_code=code_file.content,
                summary="No validation improvements needed",
                fortifier_name=self.name,
            )

        logger.info(
            "validation_suggestions_found",
            count=len(suggestions),
            file_path=code_file.path,
        )

        prompt = self._build_validation_prompt(code_file, suggestions)

        try:
            response = await self._llm_provider.complete_async(
                system_prompt="You are a security expert. Add input validation to Python functions. Return ONLY the modified code.",
                user_prompt=prompt,
                temperature=0.2,
                max_tokens=3000,
            )

            fortified_code = self._extract_code_from_markdown(
                response, code_file.content
            )

            actions = [
                FortificationAction(
                    type=FortificationActionType.INPUT_VALIDATION,
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
                summary=f"Added validation for {len(suggestions)} parameters",
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

    def _analyze_validation(self, code: str) -> List[ValidationSuggestion]:
        """Analyze code for missing input validation."""
        suggestions = []
        lines = code.split("\n")

        for i, line in enumerate(lines):
            stripped_line = line.strip()
            line_number = i + 1

            # Detect function definitions
            if stripped_line.startswith("def "):
                params = self._extract_parameters(stripped_line)

                for param in params:
                    # Skip self, cls, *args, **kwargs
                    if param in ["self", "cls"] or param.startswith("*"):
                        continue

                    # Check if validation exists
                    if not self._has_validation_for_param(lines, i, param):
                        suggestions.append(
                            ValidationSuggestion(
                                line_number=line_number,
                                parameter_name=param,
                                description=f"Parameter '{param}' should be validated",
                                severity="High",
                            )
                        )

        return suggestions

    @staticmethod
    def _extract_parameters(function_def: str) -> List[str]:
        """Extract parameter names from function definition."""
        try:
            # Extract content between parentheses
            start = function_def.index("(")
            end = function_def.index(")")
            params_str = function_def[start + 1 : end]

            # Split by comma and extract parameter names
            params = []
            for param in params_str.split(","):
                param = param.strip()
                if not param:
                    continue

                # Handle type hints (param: Type)
                if ":" in param:
                    param = param.split(":")[0].strip()

                # Handle default values (param=default)
                if "=" in param:
                    param = param.split("=")[0].strip()

                params.append(param)

            return params
        except (ValueError, IndexError):
            return []

    @staticmethod
    def _has_validation_for_param(
        lines: List[str], func_line: int, param: str
    ) -> bool:
        """Check if parameter has validation."""
        # Look in next 10 lines for validation
        for i in range(func_line + 1, min(func_line + 11, len(lines))):
            line = lines[i].strip()

            # Check for common validation patterns
            if any(
                [
                    f"if not {param}" in line,
                    f"if {param} is None" in line,
                    f"raise ValueError" in line and param in line,
                    f"assert {param}" in line,
                ]
            ):
                return True

        return False

    @staticmethod
    def _build_validation_prompt(
        code_file: CodeFile, suggestions: List[ValidationSuggestion]
    ) -> str:
        """Build LLM prompt for validation."""
        params_list = "\n".join(
            f"- Line {s.line_number}: {s.description}" for s in suggestions
        )

        return f"""Add input validation to this Python code:

Parameters needing validation:
{params_list}

Code:
```python
{code_file.content}
```

Add validation checks at function entry (type checking, null checks, range validation).
Use clear error messages. Return only the modified code."""
