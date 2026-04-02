"""
Confirmation gate helpers for destructive CLI operations.

Provides a consistent pattern for commands that delete or reset persistent
state: interactive prompt that defaults to N, with a --yes/-y bypass flag
and automatic CI-mode bypass when CI=true or GITHUB_ACTIONS=true.
"""

import os
import sys


def is_ci_environment() -> bool:
    """Return True when running in a CI environment (non-interactive).

    Detects common CI environment variables so destructive commands can
    skip the interactive prompt automatically without requiring --yes.
    Supported: CI=true, GITHUB_ACTIONS=true, GITLAB_CI=true,
               CIRCLECI=true, TRAVIS=true, BITBUCKET_BUILD_NUMBER set.
    """
    ci_vars = [
        "CI",
        "GITHUB_ACTIONS",
        "GITLAB_CI",
        "CIRCLECI",
        "TRAVIS",
    ]
    for var in ci_vars:
        if os.environ.get(var, "").lower() in ("true", "1", "yes"):
            return True
    # Bitbucket Pipelines sets BITBUCKET_BUILD_NUMBER (non-empty)
    if os.environ.get("BITBUCKET_BUILD_NUMBER", ""):
        return True
    return False


def confirm_destructive_operation(
    prompt: str,
    *,
    yes: bool = False,
) -> bool:
    """Prompt the user to confirm a destructive operation.

    Args:
        prompt: Human-readable description of what will be destroyed.
            Will be formatted as: "This will <prompt>. Are you sure? [y/N] "
        yes: Pre-confirmed flag (from --yes/-y CLI option). When True,
            the prompt is skipped and the operation proceeds immediately.

    Returns:
        True  — operation confirmed and should proceed.
        False — user declined (or stdin is not a tty), operation aborted.

    Behaviour:
        - CI environment (CI=true / GITHUB_ACTIONS=true): auto-confirms,
          prints a notice so the log is clear about what happened.
        - ``yes=True``: auto-confirms, prints a notice.
        - Interactive terminal: shows prompt, defaults to N on empty input.
        - Non-interactive (piped stdin): returns False to fail safe.
    """
    if yes:
        print(f"[--yes flag set] Proceeding with: {prompt}")
        return True

    if is_ci_environment():
        print(f"[CI environment detected] Auto-confirming: {prompt}")
        return True

    # Non-interactive stdin (piped / redirected) — fail safe
    if not sys.stdin.isatty():
        print(f"Non-interactive shell detected. Skipping: {prompt}")
        print("Re-run interactively or use --yes to confirm.")
        return False

    answer = input(f"This will {prompt}. Are you sure? [y/N] ").strip().lower()
    return answer in ("y", "yes")
