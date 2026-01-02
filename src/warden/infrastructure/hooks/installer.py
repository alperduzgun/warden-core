"""
Git hooks installer for Warden.

Manages installation and uninstallation of Git hooks.
"""

from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass
import subprocess

from warden.infrastructure.hooks.pre_commit import PreCommitHook
from warden.infrastructure.hooks.pre_push import PrePushHook
from warden.infrastructure.hooks.commit_message_hook import CommitMessageHook


@dataclass
class HookInstallResult:
    """Result of hook installation."""

    hook_name: str
    installed: bool
    message: str
    already_existed: bool = False


class HookInstaller:
    """Manages Git hooks installation for Warden."""

    SUPPORTED_HOOKS = {
        "pre-commit": PreCommitHook,
        "pre-push": PrePushHook,
        "commit-msg": CommitMessageHook,
    }

    @staticmethod
    def find_git_dir(start_path: Optional[Path] = None) -> Optional[Path]:
        """
        Find .git directory by traversing up from start_path.

        Args:
            start_path: Starting directory (default: current directory)

        Returns:
            Path to .git directory or None
        """
        if start_path is None:
            start_path = Path.cwd()

        current = start_path.resolve()

        while current != current.parent:
            git_dir = current / ".git"
            if git_dir.is_dir():
                return git_dir
            current = current.parent

        return None

    @staticmethod
    def install_hooks(
        hooks: Optional[List[str]] = None,
        git_dir: Optional[Path] = None,
        force: bool = False,
    ) -> List[HookInstallResult]:
        """
        Install Git hooks.

        Args:
            hooks: List of hook names to install (default: all)
            git_dir: Path to .git directory (auto-detected if None)
            force: Overwrite existing hooks

        Returns:
            List of installation results
        """
        if git_dir is None:
            git_dir = HookInstaller.find_git_dir()
            if git_dir is None:
                return [
                    HookInstallResult(
                        hook_name="all",
                        installed=False,
                        message="Not a git repository",
                    )
                ]

        if hooks is None:
            hooks = list(HookInstaller.SUPPORTED_HOOKS.keys())

        results = []

        for hook_name in hooks:
            if hook_name not in HookInstaller.SUPPORTED_HOOKS:
                results.append(
                    HookInstallResult(
                        hook_name=hook_name,
                        installed=False,
                        message=f"Unsupported hook: {hook_name}",
                    )
                )
                continue

            hook_class = HookInstaller.SUPPORTED_HOOKS[hook_name]

            # Check if already installed
            already_existed = hook_class.is_installed(git_dir)

            # Install
            installed = hook_class.install(git_dir, force=force)

            if installed:
                message = "Installed successfully"
                if already_existed and force:
                    message = "Reinstalled (overwrote existing)"
            else:
                if already_existed:
                    message = "Already installed (use --force to overwrite)"
                else:
                    message = "Failed to install"

            results.append(
                HookInstallResult(
                    hook_name=hook_name,
                    installed=installed,
                    message=message,
                    already_existed=already_existed,
                )
            )

        return results

    @staticmethod
    def uninstall_hooks(
        hooks: Optional[List[str]] = None,
        git_dir: Optional[Path] = None,
    ) -> List[HookInstallResult]:
        """
        Uninstall Git hooks.

        Args:
            hooks: List of hook names to uninstall (default: all)
            git_dir: Path to .git directory (auto-detected if None)

        Returns:
            List of uninstallation results
        """
        if git_dir is None:
            git_dir = HookInstaller.find_git_dir()
            if git_dir is None:
                return [
                    HookInstallResult(
                        hook_name="all",
                        installed=False,
                        message="Not a git repository",
                    )
                ]

        if hooks is None:
            hooks = list(HookInstaller.SUPPORTED_HOOKS.keys())

        results = []

        for hook_name in hooks:
            if hook_name not in HookInstaller.SUPPORTED_HOOKS:
                results.append(
                    HookInstallResult(
                        hook_name=hook_name,
                        installed=False,
                        message=f"Unsupported hook: {hook_name}",
                    )
                )
                continue

            hook_class = HookInstaller.SUPPORTED_HOOKS[hook_name]

            # Uninstall
            uninstalled = hook_class.uninstall(git_dir)

            if uninstalled:
                message = "Uninstalled successfully"
            else:
                message = "Hook not found or not a Warden hook"

            results.append(
                HookInstallResult(
                    hook_name=hook_name,
                    installed=False,
                    message=message,
                )
            )

        return results

    @staticmethod
    def list_hooks(git_dir: Optional[Path] = None) -> Dict[str, bool]:
        """
        List installed Warden hooks.

        Args:
            git_dir: Path to .git directory (auto-detected if None)

        Returns:
            Dictionary of hook_name -> is_installed
        """
        if git_dir is None:
            git_dir = HookInstaller.find_git_dir()
            if git_dir is None:
                return {}

        status = {}

        for hook_name, hook_class in HookInstaller.SUPPORTED_HOOKS.items():
            status[hook_name] = hook_class.is_installed(git_dir)

        return status

    @staticmethod
    def validate_git_repository(path: Optional[Path] = None) -> bool:
        """
        Validate that path is inside a Git repository.

        Args:
            path: Path to check (default: current directory)

        Returns:
            True if valid Git repo, False otherwise
        """
        git_dir = HookInstaller.find_git_dir(path)
        return git_dir is not None

    @staticmethod
    def get_git_config(key: str, git_dir: Optional[Path] = None) -> Optional[str]:
        """
        Get Git configuration value.

        Args:
            key: Git config key (e.g., "user.name")
            git_dir: Path to .git directory

        Returns:
            Config value or None
        """
        try:
            result = subprocess.run(
                ["git", "config", "--get", key],
                capture_output=True,
                text=True,
                check=False,
            )

            if result.returncode == 0:
                return result.stdout.strip()

            return None

        except Exception:
            return None
