"""Shared heuristics for triage file classification.

Used by both ``TriageService`` (LLM triage) and the single-tier bypass
in ``PipelinePhaseRunner`` to classify files without LLM calls.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from warden.validation.domain.frame import CodeFile

# Extensions that never contain security-relevant logic.
_SAFE_EXTENSIONS: frozenset[str] = frozenset({
    ".md", ".txt", ".rst", ".json", ".yaml", ".yml", ".css", ".scss",
    ".html", ".xml", ".csv", ".lock", ".svg", ".png", ".jpg", ".jpeg",
    ".gif", ".ico", ".woff", ".woff2", ".eot", ".ttf", ".map",
    # Python type-stubs / packaging metadata
    ".pyi", ".typed", ".toml", ".ini", ".cfg",
})

# Directory segments that indicate non-production code.
_SAFE_DIR_SEGMENTS: tuple[str, ...] = (
    "/tests/", "/test/", "/docs/", "/migrations/", "/node_modules/",
    "/dist/", "/build/", "/__pycache__/", "/site-packages/",
    "/.git/", "/.tox/", "/.mypy_cache/", "/.pytest_cache/",
    "/.venv/", "/venv/", "/.eggs/",
)

# Filenames that are structurally safe regardless of extension.
_SAFE_FILENAMES: frozenset[str] = frozenset({
    "__init__.py", "__main__.py", "conftest.py", "_version.py",
    "setup.py", "setup.cfg", "pyproject.toml", "poetry.lock",
    "Makefile", "Dockerfile", ".dockerignore", ".gitignore",
    ".editorconfig", ".flake8", ".pylintrc", "tox.ini",
    "requirements.txt", "requirements-dev.txt",
    "MANIFEST.in", "LICENSE", "CHANGELOG.md", "CONTRIBUTING.md",
})

# Minimum content size for a file to warrant LLM triage.
_MIN_CONTENT_LENGTH = 300

# Minimum line count for a file to warrant LLM triage.
_MIN_LINE_COUNT = 30


def is_heuristic_safe(code_file: CodeFile) -> bool:
    """Return True if *code_file* can safely skip LLM triage.

    This function is intentionally conservative: a ``True`` result means the
    file will be routed to the FAST lane (regex / rule-based analysis only).
    When in doubt the function returns ``False`` so that the file proceeds
    to LLM-based triage.
    """
    path_lower = str(code_file.path).lower()

    # 1. Safe by extension
    _, ext = os.path.splitext(path_lower)
    if ext in _SAFE_EXTENSIONS:
        return True

    # 2. Safe by filename
    basename = os.path.basename(path_lower)
    if basename in _SAFE_FILENAMES:
        return True

    # 3. Safe by directory
    # Normalise to forward-slash for cross-platform matching and ensure
    # leading-segment matches work (e.g. ".git/objects/..." → "/.git/...")
    path_fwd = "/" + path_lower.replace("\\", "/").lstrip("/")
    if any(seg in path_fwd for seg in _SAFE_DIR_SEGMENTS):
        return True

    # 4. Config / settings files (heuristic keyword match)
    if "config" in basename or "settings" in basename:
        return True

    # 5. Very small files (< 300 chars or < 30 lines)
    if len(code_file.content) < _MIN_CONTENT_LENGTH:
        return True
    if hasattr(code_file, "line_count") and code_file.line_count < _MIN_LINE_COUNT:
        return True

    return False
