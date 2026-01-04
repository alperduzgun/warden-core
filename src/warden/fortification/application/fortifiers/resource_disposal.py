"""
Resource Disposal Fortifier

Ensures proper resource cleanup using context managers (with statements).
Detects file handles, database connections, network sockets without proper disposal.
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
class DisposalSuggestion:
    """Represents a resource disposal suggestion."""

    line_number: int
    resource_type: str
    description: str
    severity: str = "High"


class ResourceDisposalFortifier(BaseFortifier):
    """
    Fortifier specialized in adding resource disposal (context managers).

    Ensures proper cleanup for:
    - File handles (open())
    - Database connections
    - Network sockets
    - HTTP clients
    - Locks and semaphores
    """

    def __init__(self):
        """Initialize Resource Disposal Fortifier."""
        try:
            self._llm_provider = create_client()
        except Exception:
            self._llm_provider = None  # LLM optional

    @property
    def name(self) -> str:
        """Fortifier name."""
        return "Resource Disposal"

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
        Fortify code by adding proper resource disposal.

        Args:
            code_file: The code file to fortify
            cancellation_token: Optional cancellation token

        Returns:
            FortificationResult with context managers added
        """
        if not code_file or not code_file.content:
            return FortificationResult(
                success=False,
                original_code="",
                fortified_code="",
                error_message="Code file is empty",
                fortifier_name=self.name,
            )

        suggestions = self._analyze_disposal(code_file.content)

        if not suggestions:
            return FortificationResult(
                success=True,
                original_code=code_file.content,
                fortified_code=code_file.content,
                summary="No resource disposal issues found",
                fortifier_name=self.name,
            )

        logger.info(
            "disposal_suggestions_found",
            count=len(suggestions),
            file_path=code_file.path,
        )

        prompt = self._build_disposal_prompt(code_file, suggestions)

        try:
            response = await self._llm_provider.complete_async(
                system_prompt="You are a resource management expert. Add context managers (with statements) to Python code for proper resource cleanup. Return ONLY the modified code.",
                user_prompt=prompt,
                temperature=0.2,
                max_tokens=3000,
            )

            fortified_code = self._extract_code_from_markdown(
                response, code_file.content
            )

            actions = [
                FortificationAction(
                    type=FortificationActionType.RESOURCE_DISPOSAL,
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
                summary=f"Added context managers for {len(suggestions)} resources",
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

    def _analyze_disposal(self, code: str) -> List[DisposalSuggestion]:
        """Analyze code for missing resource disposal."""
        suggestions = []
        lines = code.split("\n")

        for i, line in enumerate(lines):
            stripped_line = line.strip()
            line_number = i + 1

            # Detect file operations without 'with'
            if "= open(" in stripped_line and not self._is_in_with_block(lines, i):
                suggestions.append(
                    DisposalSuggestion(
                        line_number=line_number,
                        resource_type="FileHandle",
                        description="File should be opened using 'with' statement",
                        severity="High",
                    )
                )

            # Detect database connections without context manager
            if any(
                pattern in stripped_line
                for pattern in [".connect(", "Connection(", "Session("]
            ) and not self._is_in_with_block(lines, i):
                suggestions.append(
                    DisposalSuggestion(
                        line_number=line_number,
                        resource_type="DatabaseConnection",
                        description="Database connection should use context manager",
                        severity="Critical",
                    )
                )

            # Detect HTTP clients without context manager
            if any(
                pattern in stripped_line
                for pattern in ["httpx.Client(", "aiohttp.ClientSession("]
            ) and not self._is_in_with_block(lines, i):
                suggestions.append(
                    DisposalSuggestion(
                        line_number=line_number,
                        resource_type="HttpClient",
                        description="HTTP client should use context manager",
                        severity="High",
                    )
                )

            # Detect locks/semaphores without context manager
            if any(
                pattern in stripped_line
                for pattern in ["Lock()", "Semaphore(", "RLock()"]
            ) and not self._is_in_with_block(lines, i):
                suggestions.append(
                    DisposalSuggestion(
                        line_number=line_number,
                        resource_type="Lock",
                        description="Lock should use 'with' statement",
                        severity="Critical",
                    )
                )

        return suggestions

    @staticmethod
    def _is_in_with_block(lines: List[str], line_index: int) -> bool:
        """Check if a line is inside a 'with' block."""
        # Check current line
        current_line = lines[line_index].strip()
        if current_line.startswith("with "):
            return True

        # Scan backwards for 'with' statement
        indent_level = len(lines[line_index]) - len(lines[line_index].lstrip())

        for i in range(line_index - 1, -1, -1):
            check_line = lines[i].strip()
            check_indent = len(lines[i]) - len(lines[i].lstrip())

            # Found 'with' at same or lower indent
            if check_line.startswith("with ") and check_indent <= indent_level:
                return True

            # Stop at function/class definition
            if check_line.startswith("def ") or check_line.startswith("class "):
                break

        return False

    @staticmethod
    def _build_disposal_prompt(
        code_file: CodeFile, suggestions: List[DisposalSuggestion]
    ) -> str:
        """Build LLM prompt for resource disposal."""
        resources_list = "\n".join(
            f"- Line {s.line_number}: {s.description} ({s.resource_type})"
            for s in suggestions
        )

        return f"""Add context managers (with statements) to this Python code:

Resources needing proper disposal:
{resources_list}

Code:
```python
{code_file.content}
```

Convert resource allocations to use 'with' statements for automatic cleanup.
Ensure all resources are properly released. Return only the modified code."""
