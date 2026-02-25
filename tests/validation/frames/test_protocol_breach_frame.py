"""
Tests for ProtocolBreachFrame.

Tests cover:
- Clean state: all injection blocks present → no findings
- Breach: mixin implemented but injection block missing → PROTOCOL_BREACH
- No frames implement mixin → no breach
- project_root_not_found → graceful skip
- frame_runner missing → graceful skip
- already_analyzed guard
- _find_mixin_implementations AST parsing
- _check_injection_blocks text matching
"""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path

import pytest

from warden.validation.domain.frame import CodeFile
from warden.validation.frames.protocol_breach.protocol_breach_frame import (
    ProtocolBreachFrame,
    _extract_base_name,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_code_file(path: str = "/fake/src/warden/foo.py") -> CodeFile:
    return CodeFile(path=path, content="", language="python")


def _frame_runner_with_all_blocks() -> str:
    """Returns frame_runner.py source with all required injection blocks."""
    return textwrap.dedent("""
        if isinstance(frame, TaintAware):
            frame.set_taint_paths(context.taint_paths)
        if isinstance(frame, DataFlowAware):
            frame.set_data_dependency_graph(context.data_dependency_graph)
        if isinstance(frame, LSPAware):
            frame.set_lsp_context(lsp_context)
    """)


def _frame_runner_missing_dataflow() -> str:
    """frame_runner.py without DataFlowAware injection."""
    return textwrap.dedent("""
        if isinstance(frame, TaintAware):
            frame.set_taint_paths(context.taint_paths)
        if isinstance(frame, LSPAware):
            frame.set_lsp_context(lsp_context)
    """)


def _frame_runner_missing_all() -> str:
    """frame_runner.py with no injection blocks."""
    return "# pipeline runner placeholder"


def _frame_source_with_mixin(mixin: str) -> str:
    """Returns a frame source that inherits from the given mixin."""
    return textwrap.dedent(f"""
        from warden.validation.domain.mixins import {mixin}, ValidationFrame

        class MyTestFrame(ValidationFrame, {mixin}):
            def set_mixin(self, data):
                self._data = data
    """)


# ---------------------------------------------------------------------------
# Unit: _extract_base_name
# ---------------------------------------------------------------------------


class TestExtractBaseName:
    def test_name_node(self):
        node = ast.parse("class Foo(Bar): pass").body[0]
        assert isinstance(node, ast.ClassDef)
        assert _extract_base_name(node.bases[0]) == "Bar"

    def test_attribute_node(self):
        node = ast.parse("class Foo(module.Mixin): pass").body[0]
        assert isinstance(node, ast.ClassDef)
        assert _extract_base_name(node.bases[0]) == "Mixin"

    def test_unknown_node(self):
        # Subscript or other exotic base
        node = ast.parse("class Foo(Generic[T]): pass").body[0]
        assert isinstance(node, ast.ClassDef)
        result = _extract_base_name(node.bases[0])
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Unit: _find_mixin_implementations
# ---------------------------------------------------------------------------


class TestFindMixinImplementations:
    def test_finds_dataflow_frame(self, tmp_path):
        frame_file = tmp_path / "my_frame.py"
        frame_file.write_text(_frame_source_with_mixin("DataFlowAware"))
        frame = ProtocolBreachFrame()
        result = frame._find_mixin_implementations(tmp_path)
        assert "MyTestFrame" in result["DataFlowAware"]
        assert result["TaintAware"] == []
        assert result["LSPAware"] == []

    def test_finds_taint_frame(self, tmp_path):
        frame_file = tmp_path / "taint_frame.py"
        frame_file.write_text(_frame_source_with_mixin("TaintAware"))
        frame = ProtocolBreachFrame()
        result = frame._find_mixin_implementations(tmp_path)
        assert "MyTestFrame" in result["TaintAware"]

    def test_finds_multiple_mixins(self, tmp_path):
        (tmp_path / "frame_a.py").write_text(_frame_source_with_mixin("DataFlowAware"))
        (tmp_path / "frame_b.py").write_text(_frame_source_with_mixin("TaintAware"))
        (tmp_path / "frame_c.py").write_text(_frame_source_with_mixin("LSPAware"))
        frame = ProtocolBreachFrame()
        result = frame._find_mixin_implementations(tmp_path)
        assert result["DataFlowAware"] == ["MyTestFrame"]
        assert result["TaintAware"] == ["MyTestFrame"]
        assert result["LSPAware"] == ["MyTestFrame"]

    def test_skips_init_files(self, tmp_path):
        init_file = tmp_path / "__init__.py"
        init_file.write_text(_frame_source_with_mixin("DataFlowAware"))
        frame = ProtocolBreachFrame()
        result = frame._find_mixin_implementations(tmp_path)
        assert result["DataFlowAware"] == []

    def test_skips_mixins_file(self, tmp_path):
        mixins_file = tmp_path / "mixins.py"
        mixins_file.write_text(_frame_source_with_mixin("DataFlowAware"))
        frame = ProtocolBreachFrame()
        result = frame._find_mixin_implementations(tmp_path)
        assert result["DataFlowAware"] == []

    def test_skips_syntax_error_files(self, tmp_path):
        bad_file = tmp_path / "bad.py"
        bad_file.write_text("class Broken(DataFlowAware:\n    pass")
        frame = ProtocolBreachFrame()
        result = frame._find_mixin_implementations(tmp_path)
        assert result["DataFlowAware"] == []

    def test_empty_dir_returns_empty(self, tmp_path):
        frame = ProtocolBreachFrame()
        result = frame._find_mixin_implementations(tmp_path)
        assert all(v == [] for v in result.values())

    def test_no_duplicate_class_names(self, tmp_path):
        """Same class appearing in multiple files should only be listed once per mixin."""
        src = _frame_source_with_mixin("DataFlowAware")
        (tmp_path / "frame_a.py").write_text(src)
        # Different class name in second file
        (tmp_path / "frame_b.py").write_text(src.replace("MyTestFrame", "AnotherFrame"))
        frame = ProtocolBreachFrame()
        result = frame._find_mixin_implementations(tmp_path)
        assert len(result["DataFlowAware"]) == 2
        assert "MyTestFrame" in result["DataFlowAware"]
        assert "AnotherFrame" in result["DataFlowAware"]


# ---------------------------------------------------------------------------
# Unit: _check_injection_blocks
# ---------------------------------------------------------------------------


class TestCheckInjectionBlocks:
    def test_all_blocks_present(self, tmp_path):
        runner = tmp_path / "frame_runner.py"
        runner.write_text(_frame_runner_with_all_blocks())
        frame = ProtocolBreachFrame()
        status = frame._check_injection_blocks(runner)
        assert status["TaintAware"] is True
        assert status["DataFlowAware"] is True
        assert status["LSPAware"] is True

    def test_missing_dataflow(self, tmp_path):
        runner = tmp_path / "frame_runner.py"
        runner.write_text(_frame_runner_missing_dataflow())
        frame = ProtocolBreachFrame()
        status = frame._check_injection_blocks(runner)
        assert status["TaintAware"] is True
        assert status["DataFlowAware"] is False
        assert status["LSPAware"] is True

    def test_missing_all(self, tmp_path):
        runner = tmp_path / "frame_runner.py"
        runner.write_text(_frame_runner_missing_all())
        frame = ProtocolBreachFrame()
        status = frame._check_injection_blocks(runner)
        assert all(v is False for v in status.values())

    def test_missing_setter_only(self, tmp_path):
        """isinstance present but setter missing → False."""
        runner = tmp_path / "frame_runner.py"
        runner.write_text("if isinstance(frame, DataFlowAware): pass")
        frame = ProtocolBreachFrame()
        status = frame._check_injection_blocks(runner)
        assert status["DataFlowAware"] is False

    def test_missing_isinstance_only(self, tmp_path):
        """setter present but isinstance missing → False."""
        runner = tmp_path / "frame_runner.py"
        runner.write_text("frame.set_data_dependency_graph(ddg)")
        frame = ProtocolBreachFrame()
        status = frame._check_injection_blocks(runner)
        assert status["DataFlowAware"] is False

    def test_nonexistent_file_returns_false(self, tmp_path):
        runner = tmp_path / "nonexistent_runner.py"
        frame = ProtocolBreachFrame()
        status = frame._check_injection_blocks(runner)
        assert all(v is False for v in status.values())


# ---------------------------------------------------------------------------
# Integration: execute_async
# ---------------------------------------------------------------------------


class TestProtocolBreachFrameExecute:
    """Tests for the full execute_async flow."""

    @pytest.fixture
    def clean_project(self, tmp_path):
        """Project where all injection blocks exist and no extra frames."""
        # Create pyproject.toml (project root marker)
        (tmp_path / "pyproject.toml").touch()

        # Create frames dir with one DataFlowAware frame
        frames_dir = tmp_path / "src/warden/validation/frames/dead_data"
        frames_dir.mkdir(parents=True)
        (frames_dir / "dead_data_frame.py").write_text(_frame_source_with_mixin("DataFlowAware"))

        # Create frame_runner.py with all injection blocks
        runner_dir = tmp_path / "src/warden/pipeline/application/orchestrator"
        runner_dir.mkdir(parents=True)
        (runner_dir / "frame_runner.py").write_text(_frame_runner_with_all_blocks())

        return tmp_path

    @pytest.fixture
    def breach_project(self, tmp_path):
        """Project with DataFlowAware frame but missing injection in frame_runner."""
        (tmp_path / "pyproject.toml").touch()

        frames_dir = tmp_path / "src/warden/validation/frames/my_frame"
        frames_dir.mkdir(parents=True)
        (frames_dir / "my_frame.py").write_text(_frame_source_with_mixin("DataFlowAware"))

        runner_dir = tmp_path / "src/warden/pipeline/application/orchestrator"
        runner_dir.mkdir(parents=True)
        (runner_dir / "frame_runner.py").write_text(_frame_runner_missing_dataflow())

        return tmp_path

    @pytest.mark.asyncio
    async def test_clean_project_no_findings(self, clean_project):
        frame = ProtocolBreachFrame()
        code_file = _make_code_file(str(clean_project / "src/warden/validation/frames/dead_data/dead_data_frame.py"))
        result = await frame.execute_async(code_file)
        assert result.status == "passed"
        assert result.issues_found == 0
        assert result.findings == []

    @pytest.mark.asyncio
    async def test_breach_project_finds_protocol_breach(self, breach_project):
        frame = ProtocolBreachFrame()
        code_file = _make_code_file(str(breach_project / "src/warden/validation/frames/my_frame/my_frame.py"))
        result = await frame.execute_async(code_file)
        assert result.status == "failed"
        assert result.issues_found == 1
        assert len(result.findings) == 1

        finding = result.findings[0]
        assert "PROTOCOL-BREACH" in finding.id
        assert "DataFlowAware" in finding.message
        assert "MyTestFrame" in finding.message
        assert finding.severity == "high"
        assert finding.is_blocker is False

    @pytest.mark.asyncio
    async def test_already_analyzed_guard(self, clean_project):
        frame = ProtocolBreachFrame()
        code_file = _make_code_file(str(clean_project / "src/warden/foo.py"))

        await frame.execute_async(code_file)  # First call
        second_result = await frame.execute_async(code_file)  # Second call

        assert second_result.metadata.get("reason") == "already_analyzed"
        assert second_result.issues_found == 0

    @pytest.mark.asyncio
    async def test_project_root_not_found_returns_skip(self):
        frame = ProtocolBreachFrame()
        # Path with no pyproject.toml anywhere up the chain (use /tmp-style path)
        code_file = _make_code_file("/nonexistent_path_xyz/src/foo.py")
        result = await frame.execute_async(code_file)
        assert result.status == "passed"
        assert result.issues_found == 0
        assert result.metadata.get("reason") in ("project_root_not_found", "frame_runner_or_frames_dir_not_found")

    @pytest.mark.asyncio
    async def test_frame_runner_missing_graceful_skip(self, tmp_path):
        (tmp_path / "pyproject.toml").touch()
        # frames_dir exists but no frame_runner.py
        frames_dir = tmp_path / "src/warden/validation/frames"
        frames_dir.mkdir(parents=True)
        # frame_runner dir doesn't exist
        frame = ProtocolBreachFrame()
        code_file = _make_code_file(str(tmp_path / "src/warden/foo.py"))
        result = await frame.execute_async(code_file)
        assert result.status == "passed"
        assert result.metadata.get("reason") == "frame_runner_or_frames_dir_not_found"

    @pytest.mark.asyncio
    async def test_no_frames_implement_mixin_no_breach(self, tmp_path):
        (tmp_path / "pyproject.toml").touch()

        # frames_dir with NO mixin implementations
        frames_dir = tmp_path / "src/warden/validation/frames"
        frames_dir.mkdir(parents=True)
        (frames_dir / "plain_frame.py").write_text("class PlainFrame:\n    pass\n")

        runner_dir = tmp_path / "src/warden/pipeline/application/orchestrator"
        runner_dir.mkdir(parents=True)
        (runner_dir / "frame_runner.py").write_text(_frame_runner_missing_all())

        frame = ProtocolBreachFrame()
        code_file = _make_code_file(str(frames_dir / "plain_frame.py"))
        result = await frame.execute_async(code_file)
        # No frames implement any mixin → no breach possible
        assert result.status == "passed"
        assert result.issues_found == 0

    @pytest.mark.asyncio
    async def test_multiple_breaches_detected(self, tmp_path):
        (tmp_path / "pyproject.toml").touch()

        frames_dir = tmp_path / "src/warden/validation/frames"
        frames_dir.mkdir(parents=True)
        # Both DataFlowAware and TaintAware implemented
        (frames_dir / "frame_a.py").write_text(_frame_source_with_mixin("DataFlowAware"))
        (frames_dir / "frame_b.py").write_text(_frame_source_with_mixin("TaintAware"))

        runner_dir = tmp_path / "src/warden/pipeline/application/orchestrator"
        runner_dir.mkdir(parents=True)
        # frame_runner has NO injection blocks
        (runner_dir / "frame_runner.py").write_text(_frame_runner_missing_all())

        frame = ProtocolBreachFrame()
        code_file = _make_code_file(str(frames_dir / "frame_a.py"))
        result = await frame.execute_async(code_file)
        assert result.status == "failed"
        assert result.issues_found == 2

        finding_ids = {f.id for f in result.findings}
        assert any("DATAFLOW" in fid or "DataFlowAware" in fid for fid in finding_ids)
        assert any("TAINT" in fid or "TaintAware" in fid for fid in finding_ids)

    @pytest.mark.asyncio
    async def test_finding_metadata(self, breach_project):
        frame = ProtocolBreachFrame()
        code_file = _make_code_file(str(breach_project / "src/warden/validation/frames/my_frame/my_frame.py"))
        result = await frame.execute_async(code_file)

        meta = result.metadata
        assert "breaches" in meta
        assert "injection_status" in meta
        assert "mixin_implementations" in meta
        assert meta["injection_status"]["DataFlowAware"] is False

    @pytest.mark.asyncio
    async def test_frame_properties(self):
        frame = ProtocolBreachFrame()
        assert frame.frame_id == "protocol_breach"
        assert frame.is_blocker is False
        assert frame.supports_verification is False

    @pytest.mark.asyncio
    async def test_finding_structure(self, breach_project):
        frame = ProtocolBreachFrame()
        code_file = _make_code_file(str(breach_project / "src/warden/validation/frames/my_frame/my_frame.py"))
        result = await frame.execute_async(code_file)

        finding = result.findings[0]
        assert finding.id.startswith("CONTRACT-PROTOCOL-BREACH-")
        assert finding.severity == "high"
        assert finding.is_blocker is False
        assert "set_data_dependency_graph" in finding.detail
        assert "isinstance" in finding.detail


# ---------------------------------------------------------------------------
# Self-test: warden codebase is clean (no breaches)
# ---------------------------------------------------------------------------


class TestWardenSelfClean:
    """Verify that warden's own frame_runner.py is clean (no PROTOCOL_BREACH)."""

    @pytest.mark.asyncio
    async def test_warden_itself_has_no_breach(self):
        """The actual warden codebase should pass ProtocolBreachFrame cleanly."""
        frame = ProtocolBreachFrame()
        # Use a real path from warden's own codebase
        import warden

        warden_src = Path(warden.__file__).parent.parent
        # Find any frame file to use as code_file trigger
        frames_dir = warden_src / "warden/validation/frames"
        if not frames_dir.exists():
            pytest.skip("warden frames directory not found")

        sample_frame = next(frames_dir.rglob("*.py"), None)
        if sample_frame is None:
            pytest.skip("No frame files found")

        code_file = _make_code_file(str(sample_frame))
        result = await frame.execute_async(code_file)

        # warden's own code should be breach-free
        assert result.status == "passed", (
            f"PROTOCOL_BREACH found in warden itself: {[f.message for f in result.findings]}"
        )
        assert result.issues_found == 0
