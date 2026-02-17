"""
Python Linter Frame (Ruff).

Standard Validation Frame for Python linting using Ruff.
Compatible with Warden Hub.
"""

import shutil
from typing import List, Optional, Any
from pathlib import Path

from warden.validation.domain.frame import ValidationFrame, FrameResult, CodeFile, Finding
from warden.validation.domain.enums import FrameCategory, FramePriority, FrameScope, FrameApplicability
from warden.shared.infrastructure.logging import get_logger
from warden.analysis.services.linter_runner import LinterRunner

logger = get_logger(__name__)


class PythonLinterFrame(ValidationFrame):
    """
    Python Linter Frame using Ruff.

    Category: LANGUAGE_SPECIFIC
    Applicability: PYTHON
    """

    # Required metadata for Hub
    name = "python_lint"  # Hub ID
    description = "Fast Python linting and code quality checks using Ruff."
    category = FrameCategory.LANGUAGE_SPECIFIC
    priority = FramePriority.HIGH
    scope = FrameScope.FILE_LEVEL
    version = "1.0.0"
    author = "Warden Team"
    applicability = [FrameApplicability.PYTHON]  # Critical for optimization

    @property
    def frame_id(self) -> str:
        return "python_lint"

    def __init__(self, config: Optional[Any] = None):
        super().__init__(config)
        self.runner = LinterRunner()
        self.executable = "ruff"
        self._is_available = None  # Lazy check

    async def detect_async(self) -> bool:
        """
        Check if tool is available.
        Can be called by Pre-Analysis or during execution.
        """
        if self._is_available is not None:
            return self._is_available

        path = shutil.which(self.executable)
        self._is_available = bool(path)

        if self._is_available:
            logger.debug("frame_tool_detected", frame=self.name, tool=self.executable)
        else:
            logger.debug("frame_tool_missing", frame=self.name, tool=self.executable)

        return self._is_available

    async def execute_async(
        self,
        code_files: List[CodeFile] | CodeFile,  # Support single or batch? Base class says single, but batch exists.
        context: Optional[Any] = None,
    ) -> FrameResult:
        """Execute ruff on files."""
        # Handle single CodeFile (standard execution)
        if hasattr(code_files, "path"):
            files = [code_files]
        else:
            files = code_files

        # 1. Availability Check (Circuit Breaker)
        if not await self.detect_async():
            return FrameResult(
                frame_id=self.frame_id,
                frame_name=self.name,
                status="warning",
                duration=0.0,
                issues_found=0,
                is_blocker=False,
                findings=[],
                metadata={
                    "status": "skipped_tool_missing",
                    "install_hint": f"Run 'pip install {self.executable}' or 'brew install {self.executable}'",
                },
            )

        # 2. Filter for Python files only (Optimization)
        py_files = [str(f.path) for f in files if f.language.lower() == "python" or str(f.path).endswith(".py")]

        if not py_files:
            return FrameResult(
                frame_id=self.frame_id,
                frame_name=self.name,
                status="passed",
                duration=0.0,
                issues_found=0,
                is_blocker=False,
                findings=[],
                metadata={"status": "skipped_no_meaningful_files"},
            )

        # 3. Construct Command
        cmd = [self.executable, "check", "--output-format=json", "--exit-zero"] + py_files

        # 4. Execute via Runner
        success, data, error = await self.runner.execute_json_command(cmd)

        if not success:
            logger.error("frame_execution_failed", frame=self.name, error=error)
            return FrameResult(
                frame_id=self.frame_id,
                frame_name=self.name,
                status="failed",
                duration=0.0,
                issues_found=0,
                is_blocker=True,
                findings=[],
                metadata={"error": f"Ruff execution failed: {error}"},
            )

        # 5. Map Findings
        findings = self._map_findings(data)

        return FrameResult(
            frame_id=self.frame_id,
            frame_name=self.name,
            status="failed" if findings else "passed",
            duration=0.1,  # Todo: real duration
            issues_found=len(findings),
            is_blocker=any(f.is_blocker for f in findings),
            findings=findings,
            metadata={
                "tool": "ruff",
                "files_scanned": len(py_files),
                "raw_issues": len(data) if isinstance(data, list) else 0,
            },
        )

    def _map_findings(self, data: Any) -> List[Finding]:
        """Map Ruff JSON output to Warden Findings."""
        if not isinstance(data, list):
            return []

        findings = []
        for v in data:
            # Map severity
            code = v.get("code", "UNKNOWN")
            severity = "low"
            if code.startswith(("E9", "F82", "SyntaxError")):
                severity = "critical"
            elif code.startswith("F"):  # Pyflakes (logic)
                severity = "high"
            elif code.startswith("E"):  # PEP8 Error
                severity = "medium"

            # Construct location string
            filename = v.get("filename", "")
            row = v.get("location", {}).get("row", 0)
            col = v.get("location", {}).get("column", 0)
            location_str = f"{Path(filename).name}:{row}"

            # Helper to map severity to bool
            is_blocking = severity in ("critical", "high")

            f = Finding(
                id=code,
                message=v.get("message", "Lint error"),
                severity=severity,
                location=location_str,
                detail=f"Rule: {code} (Ruff)",
                code=None,  # Context not always provided in simpe JSON, Ruff has fix options
                line=row,
                column=col,
                is_blocker=is_blocking,
            )
            findings.append(f)
        return findings
