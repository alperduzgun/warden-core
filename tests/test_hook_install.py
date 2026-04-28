"""
Tests for HookInstaller and `warden hooks` CLI.
"""

import os
import tempfile
from pathlib import Path

import pytest

from warden.infrastructure.hooks.installer import HookInstaller


@pytest.fixture
def mock_git_repo():
    """Create a temporary directory with a .git/hooks folder."""
    with tempfile.TemporaryDirectory() as tmp:
        git_dir = Path(tmp) / ".git"
        hooks_dir = git_dir / "hooks"
        hooks_dir.mkdir(parents=True)
        yield git_dir


class TestHookInstaller:
    """Unit tests for HookInstaller static methods."""

    def test_find_git_dir_finds_git(self, mock_git_repo):
        """find_git_dir should locate .git when starting inside it."""
        found = HookInstaller.find_git_dir(mock_git_repo.parent)
        assert found is not None
        assert found.name == ".git"

    def test_find_git_dir_none_outside_repo(self):
        """find_git_dir should return None outside any git repo."""
        with tempfile.TemporaryDirectory() as tmp:
            found = HookInstaller.find_git_dir(Path(tmp))
            assert found is None

    def test_install_hooks_creates_pre_commit(self, mock_git_repo):
        """install_hooks should create pre-commit hook script."""
        results = HookInstaller.install_hooks(
            hooks=["pre-commit"],
            git_dir=mock_git_repo,
        )
        assert len(results) == 1
        assert results[0].installed is True
        assert results[0].hook_name == "pre-commit"
        hook_path = mock_git_repo / "hooks" / "pre-commit"
        assert hook_path.exists()
        content = hook_path.read_text()
        assert "warden" in content

    def test_install_hooks_skips_existing_without_force(self, mock_git_repo):
        """install_hooks should skip existing hooks without --force."""
        hook_path = mock_git_repo / "hooks" / "pre-commit"
        hook_path.write_text("#!/bin/sh\necho existing\n")
        results = HookInstaller.install_hooks(
            hooks=["pre-commit"],
            git_dir=mock_git_repo,
            force=False,
        )
        assert results[0].installed is False
        assert "already" in results[0].message.lower() or "failed" in results[0].message.lower()

    def test_install_hooks_overwrites_with_force(self, mock_git_repo):
        """install_hooks should overwrite existing hooks with --force."""
        hook_path = mock_git_repo / "hooks" / "pre-commit"
        hook_path.write_text("#!/bin/sh\necho existing\n")
        results = HookInstaller.install_hooks(
            hooks=["pre-commit"],
            git_dir=mock_git_repo,
            force=True,
        )
        assert results[0].installed is True
        content = hook_path.read_text()
        assert "warden" in content

    def test_uninstall_hooks_removes_warden_hooks(self, mock_git_repo):
        """uninstall_hooks should remove hooks with warden marker."""
        HookInstaller.install_hooks(
            hooks=["pre-commit"],
            git_dir=mock_git_repo,
        )
        results = HookInstaller.uninstall_hooks(
            hooks=["pre-commit"],
            git_dir=mock_git_repo,
        )
        assert results[0].installed is False
        hook_path = mock_git_repo / "hooks" / "pre-commit"
        assert not hook_path.exists()

    def test_list_hooks_shows_status(self, mock_git_repo):
        """list_hooks should reflect installed hooks."""
        HookInstaller.install_hooks(
            hooks=["pre-commit"],
            git_dir=mock_git_repo,
        )
        status = HookInstaller.list_hooks(git_dir=mock_git_repo)
        assert status["pre-commit"] is True
        assert status["pre-push"] is False
        assert status["commit-msg"] is False


class TestHooksCli:
    """Smoke tests for `warden hooks` CLI commands via Typer runner."""

    def test_hooks_status_shows_installed(self, mock_git_repo):
        """`warden hooks status` should display hook statuses."""
        from typer.testing import CliRunner
        from warden.main import app

        runner = CliRunner()
        # Change cwd so HookInstaller finds our mock repo
        orig_cwd = os.getcwd()
        os.chdir(mock_git_repo.parent)
        try:
            HookInstaller.install_hooks(hooks=["pre-commit"])
            result = runner.invoke(app, ["hooks", "status"])
            assert result.exit_code == 0
            assert "pre-commit" in result.output
        finally:
            os.chdir(orig_cwd)

    def test_hooks_install_creates_hook(self, mock_git_repo):
        """`warden hooks install pre-commit` should create the hook."""
        from typer.testing import CliRunner
        from warden.main import app

        runner = CliRunner()
        orig_cwd = os.getcwd()
        os.chdir(mock_git_repo.parent)
        try:
            result = runner.invoke(app, ["hooks", "install", "pre-commit"])
            assert result.exit_code == 0
            hook_path = mock_git_repo / "hooks" / "pre-commit"
            assert hook_path.exists()
        finally:
            os.chdir(orig_cwd)

    def test_hooks_uninstall_removes_hook(self, mock_git_repo):
        """`warden hooks uninstall pre-commit` should remove the hook."""
        from typer.testing import CliRunner
        from warden.main import app

        runner = CliRunner()
        orig_cwd = os.getcwd()
        os.chdir(mock_git_repo.parent)
        try:
            HookInstaller.install_hooks(hooks=["pre-commit"])
            result = runner.invoke(app, ["hooks", "uninstall", "pre-commit"])
            assert result.exit_code == 0
            hook_path = mock_git_repo / "hooks" / "pre-commit"
            assert not hook_path.exists()
        finally:
            os.chdir(orig_cwd)
