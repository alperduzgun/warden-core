"""E2E tests for `warden context` commands.

Covers:
- help is available via root app
- detect --dry-run prints YAML with expected keys
- apply (from AGENTS.md) merges commands into .warden/context.yaml
"""

from pathlib import Path

import pytest
from warden.main import app


@pytest.mark.e2e
def test_context_help(runner):
    result = runner.invoke(app, ["context", "--help"])
    assert result.exit_code == 0
    assert "Detect and manage project context" in result.stdout


@pytest.mark.e2e
def test_context_detect_dry_run(runner, isolated_project, monkeypatch):
    monkeypatch.chdir(isolated_project)
    # minimal pyproject to influence style
    (Path("pyproject.toml")).write_text("""
[tool.ruff]
line-length = 100
[tool.ruff.format]
indent-style = "space"
quote-style = "double"
""",
        encoding="utf-8",
    )

    res = runner.invoke(app, ["context", "detect", "--dry-run"])
    assert res.exit_code == 0
    out = res.stdout
    # verify YAML contains top-level keys
    assert "structure:" in out
    assert "style:" in out
    assert "testing:" in out
    assert "commands:" in out


@pytest.mark.e2e
def test_context_apply_from_agents(runner, isolated_project, monkeypatch):
    monkeypatch.chdir(isolated_project)
    # create a minimal AGENTS.md
    Path("AGENTS.md").write_text(
        """
Linter & format:
- ruff check .
- ruff format .

Run tests:
- pytest -q

Scan:
- warden scan
""",
        encoding="utf-8",
    )

    res = runner.invoke(app, ["context", "apply"])
    assert res.exit_code == 0
    ctx_path = Path(".warden/context.yaml")
    assert ctx_path.exists(), "context.yaml should be created"
    content = ctx_path.read_text(encoding="utf-8")
    # Verify commands merged
    assert "ruff check" in content
    assert "pytest -q" in content
    assert "warden scan" in content


@pytest.mark.e2e
def test_pre_analysis_loads_user_context(isolated_project, monkeypatch):
    """Ensure .warden/context.yaml is loaded into ProjectContext during PRE-ANALYSIS."""
    from warden.analysis.application.pre_analysis_phase import PreAnalysisPhase
    from warden.validation.domain.frame import CodeFile
    from warden.pipeline.domain.enums import AnalysisLevel

    monkeypatch.chdir(isolated_project)
    (Path(".warden")).mkdir(exist_ok=True)
    (Path(".warden/context.yaml")).write_text(
        """
style:
  line_length: 88
  indent: space
        """,
        encoding="utf-8",
    )
    # Create a trivial source file
    src = Path("src"); src.mkdir(exist_ok=True)
    f = src / "app.py"; f.write_text("print('hi')\n", encoding="utf-8")

    phase = PreAnalysisPhase(Path.cwd(), config={"analysis_level": AnalysisLevel.BASIC})
    res = None
    # Fallback: direct event loop for basic environment
    if res is None:
        import asyncio
        loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
        res = loop.run_until_complete(
            phase.execute_async([CodeFile(path=str(f), content=f.read_text(), language="python")], None)
        )
        loop.close()
    pc = res.project_context
    # user_context is persisted under spec_analysis
    assert pc.spec_analysis.get("user_context"), "user_context should be loaded into project_context"
    assert pc.conventions.max_line_length == 88, (
        f"Expected 88 from context.yaml, got {pc.conventions.max_line_length} (load failed?)"
    )


@pytest.mark.e2e
def test_orphan_frame_skips_test_files_with_context(isolated_project, monkeypatch):
    """OrphanFrame should skip files under tests/ or matching naming when context says so."""
    from warden.validation.frames.orphan.orphan_frame import OrphanFrame
    from warden.validation.domain.frame import CodeFile
    from warden.analysis.domain.project_context import ProjectContext

    monkeypatch.chdir(isolated_project)
    (Path(".warden")).mkdir(exist_ok=True)
    (Path(".warden/context.yaml")).write_text(
        """
structure:
  tests: [tests]
testing:
  naming: ["test_*.py"]
""",
        encoding="utf-8",
    )
    # dummy test file
    tdir = Path("tests"); tdir.mkdir(exist_ok=True)
    tf = tdir / "test_demo.py"; tf.write_text("def test_x(): pass\n", encoding="utf-8")

    # Frame with injected project_context carrying user_context
    frame = OrphanFrame(config={"ignore_test_files": True})
    pc = ProjectContext()
    pc.spec_analysis["user_context"] = {
        "structure": {"tests": ["tests"]},
        "testing": {"naming": ["test_*.py"]},
    }
    frame.project_context = pc  # type: ignore[attr-defined]

    cf = CodeFile(path=str(tf), content=tf.read_text(), language="python")
    assert frame._is_applicable(cf) is False, "OrphanFrame should skip test files by context"
