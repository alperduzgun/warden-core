"""Centralized CI environment detection.

Single source of truth for CI detection across the codebase.
Replaces scattered inline checks in config.py, ollama.py, orchestrated.py, etc.
"""

import os
import sys
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class CIEnvironment:
    """Immutable result of CI environment detection."""

    is_ci: bool
    platform: str | None = None
    is_headless: bool = True


def _is_set(var: str) -> bool:
    """Check if env var is set to a truthy value."""
    val = os.environ.get(var, "").strip().lower()
    return val not in ("", "0", "false", "no")


@lru_cache(maxsize=1)
def detect_ci_environment() -> CIEnvironment:
    """Detect CI environment from environment variables.

    Cached — env vars don't change mid-process.
    """
    if _is_set("GITHUB_ACTIONS"):
        return CIEnvironment(is_ci=True, platform="github_actions")
    if _is_set("GITLAB_CI"):
        return CIEnvironment(is_ci=True, platform="gitlab_ci")
    if os.environ.get("JENKINS_URL") or os.environ.get("JENKINS_HOME"):
        return CIEnvironment(is_ci=True, platform="jenkins")
    if _is_set("CIRCLECI"):
        return CIEnvironment(is_ci=True, platform="circleci")
    if _is_set("TRAVIS"):
        return CIEnvironment(is_ci=True, platform="travis")
    if _is_set("BITBUCKET_PIPELINE"):
        return CIEnvironment(is_ci=True, platform="bitbucket")
    if os.environ.get("CODEBUILD_BUILD_ID"):
        return CIEnvironment(is_ci=True, platform="aws_codebuild")
    if _is_set("TF_BUILD"):
        return CIEnvironment(is_ci=True, platform="azure_devops")
    if _is_set("CI"):
        return CIEnvironment(is_ci=True, platform="generic")

    return CIEnvironment(is_ci=False, platform=None, is_headless=not sys.stdin.isatty())


def is_ci() -> bool:
    """Convenience shorthand."""
    return detect_ci_environment().is_ci
