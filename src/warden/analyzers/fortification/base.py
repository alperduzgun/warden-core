"""
Base Fortifier Interface

Abstract base class for all fortifiers.
Follows Python ABC pattern (not C# interfaces).
"""

from abc import ABC, abstractmethod
from typing import Optional

from warden.analyzers.fortification.models import FortificationResult, FortifierPriority
from warden.validation.domain.frame import CodeFile


class BaseFortifier(ABC):
    """
    Abstract base class for code fortifiers.

    Each fortifier implements a specific safety improvement:
    - Error handling
    - Logging
    - Input validation
    - Resource disposal
    - Null checks
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Fortifier name (e.g., 'Error Handling')."""
        pass

    @property
    @abstractmethod
    def priority(self) -> FortifierPriority:
        """Execution priority."""
        pass

    @abstractmethod
    async def fortify_async(
        self,
        code_file: CodeFile,
        cancellation_token: Optional[str] = None,
    ) -> FortificationResult:
        """
        Fortify code by adding safety measures.

        Args:
            code_file: The code file to fortify
            cancellation_token: Optional cancellation token

        Returns:
            FortificationResult with modified code and actions
        """
        pass

    def _extract_code_from_markdown(self, response: str, fallback: str) -> str:
        """
        Extract code from markdown code blocks.

        Args:
            response: LLM response (may contain ```language blocks)
            fallback: Fallback code if extraction fails

        Returns:
            Extracted code or fallback
        """
        lines = response.split("\n")
        in_code_block = False
        code_lines = []

        for line in lines:
            stripped = line.strip()

            if stripped.startswith("```"):
                in_code_block = not in_code_block
                continue

            if in_code_block:
                code_lines.append(line)

        return "\n".join(code_lines) if code_lines else fallback
