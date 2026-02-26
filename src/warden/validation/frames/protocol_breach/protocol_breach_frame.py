"""
ProtocolBreachFrame — detects PROTOCOL_BREACH contract violations.

A PROTOCOL_BREACH occurs when a ValidationFrame implements a capability mixin
(TaintAware, DataFlowAware, LSPAware) but the pipeline's frame_runner.py is
missing the corresponding injection block.

This frame is ONLY active when contract_mode=True (opt-in).
No LLM required — pure AST + text analysis.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from warden.validation.domain.enums import (
    FrameCategory,
    FramePriority,
    FrameScope,
)
from warden.validation.domain.frame import (
    CodeFile,
    Finding,
    FrameResult,
    ValidationFrame,
)

if TYPE_CHECKING:
    from warden.pipeline.domain.pipeline_context import PipelineContext


# Mixin → injection method mapping
# Each mixin requires: isinstance(frame, MixinName) + frame.setter_method() in frame_runner
_MIXIN_PROTOCOL: dict[str, str] = {
    "TaintAware": "set_taint_paths",
    "DataFlowAware": "set_data_dependency_graph",
    "LSPAware": "set_lsp_context",
}

# Relative paths within the project
_FRAMES_REL_PATH = "src/warden/validation/frames"
_FRAME_RUNNER_REL_PATH = "src/warden/pipeline/application/orchestrator/frame_runner.py"

# Files to exclude from mixin implementation search (the mixins themselves, base classes)
_EXCLUDE_FILENAMES = {"mixins.py", "__init__.py"}


class ProtocolBreachFrame(ValidationFrame):
    """
    Detects PROTOCOL_BREACH contract violations.

    A breach is detected when:
    - A ValidationFrame subclass implements a known capability mixin
      (TaintAware, DataFlowAware, LSPAware)
    - BUT frame_runner.py is missing the corresponding injection block
      (isinstance check + setter call)

    This frame:
    - Runs once per project (self._analyzed guard)
    - Operates via AST scan of the frame files and frame_runner.py
    - Requires no DDG injection — self-contained
    - is_blocker=False (informational)
    - No LLM calls
    """

    name: str = "Protocol Breach Detector"
    description: str = "Detects frames implementing mixins without injection protocol in frame_runner"
    category: FrameCategory = FrameCategory.GLOBAL
    priority: FramePriority = FramePriority.MEDIUM
    scope: FrameScope = FrameScope.FILE_LEVEL
    is_blocker: bool = False
    supports_verification: bool = False

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self._analyzed: bool = False
        self._project_root: Path | None = None

    @property
    def frame_id(self) -> str:
        return "protocol_breach"

    async def execute_async(self, code_file: CodeFile, context: PipelineContext | None = None) -> FrameResult:
        """
        Run protocol breach analysis.

        NOTE: This frame operates PROJECT-WIDE, not per-file.
        Only the first call runs analysis; subsequent calls return empty results.
        Project root is inferred from the first code_file.path received.
        """
        start = time.monotonic()

        if self._analyzed:
            return FrameResult(
                frame_id=self.frame_id,
                frame_name=self.name,
                status="passed",
                duration=time.monotonic() - start,
                issues_found=0,
                is_blocker=self.is_blocker,
                findings=[],
                metadata={"skipped": True, "reason": "already_analyzed"},
            )

        self._analyzed = True

        # Infer project root from first code file path
        project_root = self._resolve_project_root(code_file.path)
        if project_root is None:
            return FrameResult(
                frame_id=self.frame_id,
                frame_name=self.name,
                status="passed",
                duration=time.monotonic() - start,
                issues_found=0,
                is_blocker=self.is_blocker,
                findings=[],
                metadata={"skipped": True, "reason": "project_root_not_found"},
            )

        frame_runner_path = project_root / _FRAME_RUNNER_REL_PATH
        frames_dir = project_root / _FRAMES_REL_PATH

        if not frame_runner_path.exists() or not frames_dir.exists():
            return FrameResult(
                frame_id=self.frame_id,
                frame_name=self.name,
                status="passed",
                duration=time.monotonic() - start,
                issues_found=0,
                is_blocker=self.is_blocker,
                findings=[],
                metadata={"skipped": True, "reason": "frame_runner_or_frames_dir_not_found"},
            )

        # Step 1: Find mixin implementations in frame files
        mixin_implementations = self._find_mixin_implementations(frames_dir)

        # Step 2: Check injection blocks in frame_runner.py
        injection_status = self._check_injection_blocks(frame_runner_path)

        # Step 3: Report breaches (mixin implemented but injection missing)
        finding_objects: list[Finding] = []
        breach_details: list[dict[str, Any]] = []

        for mixin_name, setter_method in _MIXIN_PROTOCOL.items():
            implementing_frames = mixin_implementations.get(mixin_name, [])
            if not implementing_frames:
                # No frames implement this mixin — no breach possible
                continue

            has_injection = injection_status.get(mixin_name, False)
            if not has_injection:
                detail = {
                    "mixin": mixin_name,
                    "setter_method": setter_method,
                    "implementing_frames": implementing_frames,
                    "missing_from": str(frame_runner_path.relative_to(project_root)),
                }
                breach_details.append(detail)
                finding_objects.append(
                    self._make_finding(
                        mixin_name=mixin_name,
                        setter_method=setter_method,
                        implementing_frames=implementing_frames,
                        frame_runner_path=frame_runner_path,
                        project_root=project_root,
                    )
                )

        return FrameResult(
            frame_id=self.frame_id,
            frame_name=self.name,
            status="failed" if finding_objects else "passed",
            duration=time.monotonic() - start,
            issues_found=len(finding_objects),
            is_blocker=self.is_blocker,
            findings=finding_objects,
            metadata={
                "gap_type": "PROTOCOL_BREACH",
                "mixins_checked": list(_MIXIN_PROTOCOL.keys()),
                "mixin_implementations": {k: v for k, v in mixin_implementations.items() if v},
                "injection_status": injection_status,
                "breaches": breach_details,
            },
        )

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    def _resolve_project_root(self, file_path: str) -> Path | None:
        """
        Walk up from file_path to find the project root.
        Identified by the presence of pyproject.toml or setup.py.
        """
        path = Path(file_path).resolve()
        for candidate in [path, *path.parents]:
            if (candidate / "pyproject.toml").exists() or (candidate / "setup.py").exists():
                return candidate
        return None

    def _find_mixin_implementations(self, frames_dir: Path) -> dict[str, list[str]]:
        """
        Scan all Python files under frames_dir for classes that inherit from known mixins.

        Returns:
            {mixin_name: [ClassName, ...]}
        """
        implementations: dict[str, list[str]] = {m: [] for m in _MIXIN_PROTOCOL}

        for py_file in frames_dir.rglob("*.py"):
            if py_file.name in _EXCLUDE_FILENAMES:
                continue
            try:
                source = py_file.read_text(encoding="utf-8")
                tree = ast.parse(source, filename=str(py_file))
            except (SyntaxError, OSError):
                continue

            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                for base in node.bases:
                    base_name = _extract_base_name(base)
                    if base_name in _MIXIN_PROTOCOL and node.name not in implementations[base_name]:
                        implementations[base_name].append(node.name)

        return implementations

    def _check_injection_blocks(self, frame_runner_path: Path) -> dict[str, bool]:
        """
        Check frame_runner.py for injection blocks for each known mixin.

        An injection block requires both:
        1. isinstance(frame, MixinName)  — the mixin type check
        2. frame.setter_method(...)       — the setter invocation

        Returns:
            {mixin_name: True if injection block exists, False otherwise}
        """
        try:
            source = frame_runner_path.read_text(encoding="utf-8")
        except OSError:
            return dict.fromkeys(_MIXIN_PROTOCOL, False)

        status: dict[str, bool] = {}
        for mixin_name, setter_method in _MIXIN_PROTOCOL.items():
            has_isinstance = f"isinstance(frame, {mixin_name})" in source
            has_setter = f"frame.{setter_method}(" in source
            status[mixin_name] = has_isinstance and has_setter

        return status

    def _make_finding(
        self,
        mixin_name: str,
        setter_method: str,
        implementing_frames: list[str],
        frame_runner_path: Path,
        project_root: Path,
    ) -> Finding:
        """Create a Finding for a PROTOCOL_BREACH."""
        frames_str = ", ".join(implementing_frames)
        relative_runner = str(frame_runner_path.relative_to(project_root))

        message = (
            f"[PROTOCOL_BREACH] Mixin '{mixin_name}' implemented by [{frames_str}] "
            f"but '{relative_runner}' is missing the injection block "
            f"(isinstance(frame, {mixin_name}) + frame.{setter_method}(...))"
        )

        safe_mixin = mixin_name.upper().replace("AWARE", "")
        finding_id = f"CONTRACT-PROTOCOL-BREACH-{safe_mixin}"

        return Finding(
            id=finding_id,
            severity="high",
            message=message,
            location=str(frame_runner_path),
            detail=(
                f"Mixin: {mixin_name}\n"
                f"Required setter: frame.{setter_method}(...)\n"
                f"Implementing frames: {frames_str}\n"
                f"Fix: Add 'if isinstance(frame, {mixin_name}): frame.{setter_method}(...)' "
                f"in {relative_runner}"
            ),
            line=0,
            is_blocker=False,
        )


# -------------------------------------------------------------------------
# AST helpers
# -------------------------------------------------------------------------


def _extract_base_name(node: ast.expr) -> str:
    """Extract class name from a base class AST node (handles Name and Attribute)."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""
