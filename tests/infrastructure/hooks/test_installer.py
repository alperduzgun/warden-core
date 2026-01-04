"""
Tests for Git hooks installer.
"""

import pytest
from pathlib import Path
import tempfile

from warden.infrastructure.hooks.installer import HookInstaller, HookInstallResult
from warden.infrastructure.hooks.pre_commit import PreCommitHook
from warden.infrastructure.hooks.pre_push import PrePushHook


class TestHookInstaller:
    """Test HookInstaller functionality."""

    def test_find_git_dir_in_git_repo(self, tmp_path):
        """Test finding .git directory in a Git repository."""
        # Create fake .git directory
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        found_git_dir = HookInstaller.find_git_dir(tmp_path)

        assert found_git_dir == git_dir

    def test_find_git_dir_parent(self, tmp_path):
        """Test finding .git directory in parent."""
        # Create .git in parent
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        # Create subdirectory
        subdir = tmp_path / "subdir" / "deep"
        subdir.mkdir(parents=True)

        found_git_dir = HookInstaller.find_git_dir(subdir)

        assert found_git_dir == git_dir

    def test_find_git_dir_not_found(self, tmp_path):
        """Test when .git directory doesn't exist."""
        found_git_dir = HookInstaller.find_git_dir(tmp_path)

        assert found_git_dir is None

    def test_install_hooks_all(self, tmp_path):
        """Test installing all hooks."""
        # Create fake .git directory
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        results = HookInstaller.install_hooks(git_dir=git_dir)

        # Should install all supported hooks
        assert len(results) == 3
        assert all(r.installed for r in results)
        assert any(r.hook_name == "pre-commit" for r in results)
        assert any(r.hook_name == "pre-push" for r in results)
        assert any(r.hook_name == "commit-msg" for r in results)

    def test_install_hooks_specific(self, tmp_path):
        """Test installing specific hooks."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        results = HookInstaller.install_hooks(
            hooks=["pre-commit"],
            git_dir=git_dir,
        )

        assert len(results) == 1
        assert results[0].hook_name == "pre-commit"
        assert results[0].installed is True

    def test_install_hooks_already_exists(self, tmp_path):
        """Test installing when hook already exists."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        # Install once
        HookInstaller.install_hooks(hooks=["pre-commit"], git_dir=git_dir)

        # Install again without force
        results = HookInstaller.install_hooks(
            hooks=["pre-commit"],
            git_dir=git_dir,
            force=False,
        )

        assert results[0].installed is False
        assert results[0].already_existed is True

    def test_install_hooks_force_overwrite(self, tmp_path):
        """Test force overwriting existing hooks."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        # Install once
        HookInstaller.install_hooks(hooks=["pre-commit"], git_dir=git_dir)

        # Install again with force
        results = HookInstaller.install_hooks(
            hooks=["pre-commit"],
            git_dir=git_dir,
            force=True,
        )

        assert results[0].installed is True
        assert results[0].already_existed is True

    def test_install_hooks_invalid_hook(self, tmp_path):
        """Test installing invalid hook name."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        results = HookInstaller.install_hooks(
            hooks=["invalid-hook"],
            git_dir=git_dir,
        )

        assert len(results) == 1
        assert results[0].installed is False
        assert "Unsupported hook" in results[0].message

    def test_install_hooks_not_git_repo(self, tmp_path):
        """Test installing hooks outside Git repository."""
        # Use find_git_dir explicitly to start search from empty tmp_path
        # so it doesn't find repo's .git
        from unittest.mock import patch
        with patch.object(HookInstaller, 'find_git_dir', return_value=None):
            results = HookInstaller.install_hooks()

        # Should return error result
        assert len(results) == 1
        assert results[0].installed is False
        assert "Not a git repository" in results[0].message

    def test_uninstall_hooks_all(self, tmp_path):
        """Test uninstalling all hooks."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        # Install hooks first
        HookInstaller.install_hooks(git_dir=git_dir)

        # Uninstall
        results = HookInstaller.uninstall_hooks(git_dir=git_dir)

        assert len(results) == 3
        assert all(not r.installed for r in results)

    def test_uninstall_hooks_specific(self, tmp_path):
        """Test uninstalling specific hook."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        # Install hooks
        HookInstaller.install_hooks(git_dir=git_dir)

        # Uninstall only pre-commit
        results = HookInstaller.uninstall_hooks(
            hooks=["pre-commit"],
            git_dir=git_dir,
        )

        assert len(results) == 1
        assert results[0].hook_name == "pre-commit"
        assert results[0].installed is False

    def test_uninstall_hooks_not_installed(self, tmp_path):
        """Test uninstalling hooks that aren't installed."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        results = HookInstaller.uninstall_hooks(git_dir=git_dir)

        assert all(not r.installed for r in results)
        assert all("not found" in r.message.lower() for r in results)

    def test_list_hooks_empty(self, tmp_path):
        """Test listing hooks when none are installed."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        status = HookInstaller.list_hooks(git_dir)

        assert isinstance(status, dict)
        assert len(status) == 3
        assert all(not is_installed for is_installed in status.values())

    def test_list_hooks_some_installed(self, tmp_path):
        """Test listing hooks when some are installed."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        # Install only pre-commit
        HookInstaller.install_hooks(hooks=["pre-commit"], git_dir=git_dir)

        status = HookInstaller.list_hooks(git_dir)

        assert status["pre-commit"] is True
        assert status["pre-push"] is False
        assert status["commit-msg"] is False

    def test_list_hooks_not_git_repo(self, tmp_path):
        """Test listing hooks outside Git repository."""
        from unittest.mock import patch
        with patch.object(HookInstaller, 'find_git_dir', return_value=None):
            status = HookInstaller.list_hooks()

        assert status == {}

    def test_validate_git_repository_valid(self, tmp_path):
        """Test validating a valid Git repository."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        is_valid = HookInstaller.validate_git_repository(tmp_path)

        assert is_valid is True

    def test_validate_git_repository_invalid(self, tmp_path):
        """Test validating an invalid Git repository."""
        # Ensure it doesn't fall back to parent git dir
        from unittest.mock import patch
        with patch.object(HookInstaller, 'find_git_dir', return_value=None):
             is_valid = HookInstaller.validate_git_repository(tmp_path)

        assert is_valid is False


class TestPreCommitHook:
    """Test PreCommitHook functionality."""

    def test_generate_script(self):
        """Test generating pre-commit hook script."""
        script = PreCommitHook.generate_script()

        assert "#!/usr/bin/env python3" in script
        assert "Warden pre-commit hook" in script
        assert '"warden",' in script
        assert '"analyze",' in script

    def test_install(self, tmp_path):
        """Test installing pre-commit hook."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        installed = PreCommitHook.install(git_dir)

        assert installed is True

        hook_path = git_dir / "hooks" / "pre-commit"
        assert hook_path.exists()
        assert hook_path.stat().st_mode & 0o111  # Executable

    def test_install_force(self, tmp_path):
        """Test force installing pre-commit hook."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        # Install once
        PreCommitHook.install(git_dir)

        # Install again with force
        installed = PreCommitHook.install(git_dir, force=True)

        assert installed is True

    def test_uninstall(self, tmp_path):
        """Test uninstalling pre-commit hook."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        # Install first
        PreCommitHook.install(git_dir)

        # Uninstall
        uninstalled = PreCommitHook.uninstall(git_dir)

        assert uninstalled is True

        hook_path = git_dir / "hooks" / "pre-commit"
        assert not hook_path.exists()

    def test_is_installed_true(self, tmp_path):
        """Test checking if hook is installed (true)."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        PreCommitHook.install(git_dir)

        is_installed = PreCommitHook.is_installed(git_dir)

        assert is_installed is True

    def test_is_installed_false(self, tmp_path):
        """Test checking if hook is installed (false)."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        is_installed = PreCommitHook.is_installed(git_dir)

        assert is_installed is False


class TestPrePushHook:
    """Test PrePushHook functionality."""

    def test_generate_script(self):
        """Test generating pre-push hook script."""
        script = PrePushHook.generate_script()

        assert "#!/usr/bin/env python3" in script
        assert "Warden pre-push hook" in script
        assert '"warden",' in script
        assert '"analyze",' in script

    def test_install(self, tmp_path):
        """Test installing pre-push hook."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        installed = PrePushHook.install(git_dir)

        assert installed is True

        hook_path = git_dir / "hooks" / "pre-push"
        assert hook_path.exists()
        assert hook_path.stat().st_mode & 0o111  # Executable

    def test_uninstall(self, tmp_path):
        """Test uninstalling pre-push hook."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        # Install first
        PrePushHook.install(git_dir)

        # Uninstall
        uninstalled = PrePushHook.uninstall(git_dir)

        assert uninstalled is True

        hook_path = git_dir / "hooks" / "pre-push"
        assert not hook_path.exists()

    def test_is_installed(self, tmp_path):
        """Test checking if hook is installed."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        # Not installed
        assert PrePushHook.is_installed(git_dir) is False

        # Install
        PrePushHook.install(git_dir)

        # Installed
        assert PrePushHook.is_installed(git_dir) is True
