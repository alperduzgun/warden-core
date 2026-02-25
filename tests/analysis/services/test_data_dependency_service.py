"""
Unit tests for DataDependencyService (#165).

Tests:
- _collect_python_files excludes known dirs
- _is_excluded recognises all EXCLUDE_DIRS entries
- build() delegates to DataDependencyBuilder and returns a DDG
- build_ddg_for_project convenience function works
- Empty project root returns empty DDG
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from warden.analysis.services.data_dependency_service import (
    EXCLUDE_DIRS,
    DataDependencyService,
    build_ddg_for_project,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_py(directory: Path, filename: str, content: str) -> Path:
    """Write a Python file and return its path."""
    path = directory / filename
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# _is_excluded
# ---------------------------------------------------------------------------


class TestIsExcluded:
    """Tests for DataDependencyService._is_excluded."""

    def test_excludes_venv_dir(self, tmp_path: Path) -> None:
        service = DataDependencyService(tmp_path)
        venv_file = tmp_path / ".venv" / "lib" / "site.py"
        venv_file.parent.mkdir(parents=True)
        venv_file.write_text("# stub", encoding="utf-8")
        assert service._is_excluded(venv_file) is True

    def test_excludes_pycache(self, tmp_path: Path) -> None:
        service = DataDependencyService(tmp_path)
        cache_file = tmp_path / "src" / "__pycache__" / "module.cpython-311.pyc"
        cache_file.parent.mkdir(parents=True)
        cache_file.write_text("", encoding="utf-8")
        assert service._is_excluded(cache_file) is True

    def test_excludes_git_dir(self, tmp_path: Path) -> None:
        service = DataDependencyService(tmp_path)
        git_file = tmp_path / ".git" / "config"
        git_file.parent.mkdir(parents=True)
        git_file.write_text("", encoding="utf-8")
        assert service._is_excluded(git_file) is True

    def test_excludes_warden_cache(self, tmp_path: Path) -> None:
        service = DataDependencyService(tmp_path)
        warden_file = tmp_path / ".warden" / "intelligence" / "code_graph.json"
        warden_file.parent.mkdir(parents=True)
        warden_file.write_text("{}", encoding="utf-8")
        assert service._is_excluded(warden_file) is True

    def test_does_not_exclude_src_files(self, tmp_path: Path) -> None:
        service = DataDependencyService(tmp_path)
        src_file = tmp_path / "src" / "module.py"
        src_file.parent.mkdir(parents=True)
        src_file.write_text("x = 1", encoding="utf-8")
        assert service._is_excluded(src_file) is False

    def test_does_not_exclude_root_py_file(self, tmp_path: Path) -> None:
        service = DataDependencyService(tmp_path)
        root_file = tmp_path / "setup.py"
        root_file.write_text("# setup", encoding="utf-8")
        assert service._is_excluded(root_file) is False

    def test_excludes_egg_info_suffix(self, tmp_path: Path) -> None:
        service = DataDependencyService(tmp_path)
        egg_file = tmp_path / "mylib.egg-info" / "PKG-INFO"
        egg_file.parent.mkdir(parents=True)
        egg_file.write_text("", encoding="utf-8")
        assert service._is_excluded(egg_file) is True

    def test_all_exclude_dirs_respected(self, tmp_path: Path) -> None:
        """Every EXCLUDE_DIRS member should cause exclusion."""
        service = DataDependencyService(tmp_path)
        for exc_dir in EXCLUDE_DIRS:
            nested = tmp_path / exc_dir / "file.py"
            nested.parent.mkdir(parents=True, exist_ok=True)
            nested.write_text("", encoding="utf-8")
            assert service._is_excluded(nested) is True, f"Expected {exc_dir!r} to be excluded"

    def test_path_outside_project_root_is_excluded(self, tmp_path: Path) -> None:
        """Files outside project_root should be excluded (safety guard)."""
        service = DataDependencyService(tmp_path / "project")
        outside_file = tmp_path / "other" / "file.py"
        outside_file.parent.mkdir(parents=True)
        outside_file.write_text("", encoding="utf-8")
        assert service._is_excluded(outside_file) is True


# ---------------------------------------------------------------------------
# _collect_python_files
# ---------------------------------------------------------------------------


class TestCollectPythonFiles:
    """Tests for DataDependencyService._collect_python_files."""

    def test_collects_src_py_files(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        f1 = _write_py(src, "a.py", "x = 1")
        f2 = _write_py(src, "b.py", "y = 2")
        service = DataDependencyService(tmp_path)
        files = service._collect_python_files()
        assert f1 in files
        assert f2 in files

    def test_skips_excluded_dirs(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        good = _write_py(src, "good.py", "")
        venv = tmp_path / ".venv" / "lib"
        venv.mkdir(parents=True)
        bad = _write_py(venv, "bad.py", "")
        service = DataDependencyService(tmp_path)
        files = service._collect_python_files()
        assert good in files
        assert bad not in files

    def test_empty_project_returns_empty_list(self, tmp_path: Path) -> None:
        service = DataDependencyService(tmp_path)
        assert service._collect_python_files() == []

    def test_returns_sorted_list(self, tmp_path: Path) -> None:
        for name in ("z.py", "a.py", "m.py"):
            _write_py(tmp_path, name, "")
        service = DataDependencyService(tmp_path)
        files = service._collect_python_files()
        assert files == sorted(files)


# ---------------------------------------------------------------------------
# build()
# ---------------------------------------------------------------------------


class TestBuild:
    """Tests for DataDependencyService.build()."""

    def test_build_returns_ddg_with_writes(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        _write_py(
            src,
            "executor.py",
            textwrap.dedent(
                """
                def run(context):
                    context.code_graph = build_graph()
                """
            ),
        )
        service = DataDependencyService(tmp_path)
        ddg = service.build()
        assert any("code_graph" in k for k in ddg.writes)

    def test_build_returns_ddg_with_reads(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        _write_py(
            src,
            "reader.py",
            textwrap.dedent(
                """
                def read(context):
                    return context.gap_report
                """
            ),
        )
        service = DataDependencyService(tmp_path)
        ddg = service.build()
        assert any("gap_report" in k for k in ddg.reads)

    def test_build_empty_project(self, tmp_path: Path) -> None:
        service = DataDependencyService(tmp_path)
        ddg = service.build()
        assert len(ddg.writes) == 0
        assert len(ddg.reads) == 0

    def test_build_excludes_venv_files(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        _write_py(src, "real.py", "context.findings = []")
        venv_src = tmp_path / ".venv" / "lib"
        venv_src.mkdir(parents=True)
        _write_py(venv_src, "fake.py", "context.taint_paths = {}")
        service = DataDependencyService(tmp_path)
        ddg = service.build()
        # .venv file has 'taint_paths'; src file has 'findings'
        # Both may or may not be present depending on FP filter — but we
        # check that the .venv path does not appear in any node's file_path
        all_file_paths = {n.file_path for nodes in ddg.writes.values() for n in nodes}
        all_file_paths |= {n.file_path for nodes in ddg.reads.values() for n in nodes}
        for fp in all_file_paths:
            assert ".venv" not in fp, f"Excluded dir appeared in DDG: {fp}"

    def test_build_syntax_error_file_is_skipped(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        _write_py(src, "bad_syntax.py", "def broken(:\n    pass")
        _write_py(src, "good.py", "context.code_graph = None")
        service = DataDependencyService(tmp_path)
        # Should not raise; bad_syntax.py is silently skipped
        ddg = service.build()
        assert any("code_graph" in k for k in ddg.writes)

    def test_build_ddg_stats_keys(self, tmp_path: Path) -> None:
        service = DataDependencyService(tmp_path)
        ddg = service.build()
        stats = ddg.stats()
        for key in ("total_fields", "write_fields", "read_fields", "dead_write_count"):
            assert key in stats


# ---------------------------------------------------------------------------
# build_ddg_for_project convenience function
# ---------------------------------------------------------------------------


class TestBuildDdgForProject:
    def test_convenience_function_returns_ddg(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        _write_py(src, "phase.py", "context.code_graph = graph")
        ddg = build_ddg_for_project(tmp_path)
        assert any("code_graph" in k for k in ddg.writes)

    def test_accepts_string_path(self, tmp_path: Path) -> None:
        ddg = build_ddg_for_project(str(tmp_path))
        assert ddg is not None
