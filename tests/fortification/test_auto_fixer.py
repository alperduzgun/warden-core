"""Tests for auto-fix with git checkpoint."""
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from warden.fortification.application.auto_fixer import AutoFixer, AutoFixResult
from warden.fortification.infrastructure.git_checkpoint import GitCheckpointManager


class TestGitCheckpointManager:
    def test_validate_syntax_valid(self, tmp_path):
        valid_file = tmp_path / "good.py"
        valid_file.write_text("x = 1\n")
        mgr = GitCheckpointManager(tmp_path)
        assert mgr.validate_syntax(valid_file) is True

    def test_validate_syntax_invalid(self, tmp_path):
        bad_file = tmp_path / "bad.py"
        bad_file.write_text("def foo(\n")
        mgr = GitCheckpointManager(tmp_path)
        assert mgr.validate_syntax(bad_file) is False

    def test_validate_syntax_non_python(self, tmp_path):
        js_file = tmp_path / "app.js"
        js_file.write_text("const x = {invalid")
        mgr = GitCheckpointManager(tmp_path)
        assert mgr.validate_syntax(js_file) is True  # Skips non-Python

    def test_record_modification(self, tmp_path):
        mgr = GitCheckpointManager(tmp_path)
        mgr.record_modification("foo.py")
        mgr.record_modification("bar.py")
        assert mgr.modified_files == ["foo.py", "bar.py"]

    def test_modified_files_returns_copy(self, tmp_path):
        mgr = GitCheckpointManager(tmp_path)
        mgr.record_modification("foo.py")
        files = mgr.modified_files
        files.append("extra.py")
        assert mgr.modified_files == ["foo.py"]

    def test_checkpoint_ref_initially_none(self, tmp_path):
        mgr = GitCheckpointManager(tmp_path)
        assert mgr.checkpoint_ref is None


class TestAutoFixResult:
    def test_summary_empty(self):
        result = AutoFixResult()
        assert result.summary == "0 applied / 0 skipped / 0 failed"

    def test_summary_with_counts(self):
        result = AutoFixResult()
        result.applied.append({"file": "a.py"})
        result.applied.append({"file": "b.py"})
        result.skipped.append({"file": "c.py"})
        result.failed.append({"file": "d.py"})
        assert result.summary == "2 applied / 1 skipped / 1 failed"

    def test_dry_run_default_false(self):
        result = AutoFixResult()
        assert result.dry_run is False


class TestAutoFixer:
    @pytest.mark.asyncio
    async def test_dry_run_no_changes(self, tmp_path):
        # Create a file
        target = tmp_path / "app.py"
        target.write_text("password = 'secret123'\n")

        fixer = AutoFixer(project_root=tmp_path, dry_run=True)
        result = await fixer.apply_fixes([{
            "auto_fixable": True,
            "file_path": "app.py",
            "original_code": "password = 'secret123'",
            "suggested_code": "password = os.environ.get('PASSWORD')",
        }])

        assert result.dry_run is True
        assert len(result.applied) == 1
        # File should NOT be changed
        assert "secret123" in target.read_text()

    @pytest.mark.asyncio
    async def test_skip_non_fixable(self, tmp_path):
        fixer = AutoFixer(project_root=tmp_path, dry_run=True)
        result = await fixer.apply_fixes([{
            "auto_fixable": False,
            "file_path": "app.py",
            "suggested_code": "fix",
        }])
        assert len(result.applied) == 0
        assert len(result.skipped) == 0

    @pytest.mark.asyncio
    async def test_skip_missing_file(self, tmp_path):
        fixer = AutoFixer(project_root=tmp_path, dry_run=False)
        result = await fixer.apply_fixes([{
            "auto_fixable": True,
            "file_path": "nonexistent.py",
            "suggested_code": "fix",
        }])
        assert len(result.skipped) == 1

    @pytest.mark.asyncio
    async def test_empty_fortifications(self, tmp_path):
        fixer = AutoFixer(project_root=tmp_path)
        result = await fixer.apply_fixes([])
        assert result.summary == "0 applied / 0 skipped / 0 failed"

    @pytest.mark.asyncio
    async def test_skip_missing_suggested_code(self, tmp_path):
        target = tmp_path / "app.py"
        target.write_text("x = 1\n")

        fixer = AutoFixer(project_root=tmp_path, dry_run=True)
        result = await fixer.apply_fixes([{
            "auto_fixable": True,
            "file_path": "app.py",
            "suggested_code": None,
        }])
        assert len(result.skipped) == 1
        assert "missing" in result.skipped[0].get("reason", "").lower()

    @pytest.mark.asyncio
    async def test_apply_fix_replaces_code(self, tmp_path):
        """Test actual file modification (without git checkpoint)."""
        target = tmp_path / "app.py"
        target.write_text("password = 'secret123'\nother_line = True\n")

        fixer = AutoFixer(project_root=tmp_path, dry_run=False)
        # Patch at the source module so the lazy import picks up the mock
        with patch(
            "warden.fortification.infrastructure.git_checkpoint.GitCheckpointManager"
        ) as MockCM:
            mock_instance = MagicMock()
            mock_instance.validate_syntax.return_value = True
            mock_instance.create_checkpoint.return_value = None
            MockCM.return_value = mock_instance

            result = await fixer.apply_fixes([{
                "auto_fixable": True,
                "file_path": "app.py",
                "original_code": "password = 'secret123'",
                "suggested_code": "password = os.environ.get('PASSWORD')",
            }])

        assert len(result.applied) == 1
        content = target.read_text()
        assert "os.environ.get('PASSWORD')" in content
        assert "secret123" not in content
        assert "other_line = True" in content

    @pytest.mark.asyncio
    async def test_rollback_on_syntax_error(self, tmp_path):
        """Test that syntax-invalid fixes are rejected."""
        target = tmp_path / "app.py"
        original_content = "x = 1\ny = 2\n"
        target.write_text(original_content)

        fixer = AutoFixer(project_root=tmp_path, dry_run=False)
        with patch(
            "warden.fortification.infrastructure.git_checkpoint.GitCheckpointManager"
        ) as MockCM:
            mock_instance = MagicMock()
            mock_instance.validate_syntax.return_value = False  # Syntax check fails
            mock_instance.create_checkpoint.return_value = None
            MockCM.return_value = mock_instance

            result = await fixer.apply_fixes([{
                "auto_fixable": True,
                "file_path": "app.py",
                "original_code": "x = 1",
                "suggested_code": "x = (",  # Invalid syntax
            }])

        assert len(result.failed) == 1
        # Original file should be unchanged (temp file was deleted, original not replaced)
        assert target.read_text() == original_content
