"""
Infrastructure module for Warden.

This module provides CI/CD integration, Git hooks, and auto-installer
capabilities for seamless Warden integration into development workflows.

Components:
- CI Integration: GitHub Actions, GitLab CI, Azure Pipelines templates
- Git Hooks: Pre-commit, pre-push, commit-msg hooks
- Auto-installer: Pip install script, Docker support
"""

from warden.infrastructure.installer import AutoInstaller
from warden.infrastructure.hooks.installer import HookInstaller

__all__ = [
    "AutoInstaller",
    "HookInstaller",
]
