"""
Static Pre-Filter for LLM Classification — Issue #618.

Runs a fast, deterministic grep/AST-based analysis on each file before the
LLM classification phase.  If the pre-filter can decide frame selection with
high confidence, the LLM call is skipped entirely, reducing latency and token
spend.

Design goals:
- Zero external dependencies (stdlib only).
- O(n) in file length — single-pass keyword scan.
- Conservative: returns None when uncertain so the LLM is always the
  tiebreaker.  False negatives (pre-filter says None, LLM handles it) are
  acceptable; false positives (wrong frame set) are not.

Usage::

    from warden.classification.application.static_pre_filter import StaticPreFilter

    result = StaticPreFilter.classify(file_path, source)
    if result is not None:
        # Use result["selected_frames"] directly — skip LLM
        ...
    else:
        # Fall through to LLM classification
        ...
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Security keyword patterns that trigger the "security" frame.
# Kept as a frozenset of lowercase tokens for O(1) membership checks after
# source is lower-cased once.
# ---------------------------------------------------------------------------
_SECURITY_KEYWORDS: frozenset[str] = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "token",
        "api_key",
        "apikey",
        "auth",
        "credential",
        "private_key",
        "access_key",
        "sql",
        "query",
        "execute",
        "exec(",
        "eval(",
        "subprocess",
        "os.system",
        "shell=true",
        "pickle.load",
        "yaml.load",
        "hashlib.md5",
        "hashlib.sha1",
        "hmac",
        "jwt",
        "bearer",
        "authorization",
        "cookie",
        "session",
        "csrf",
        "xss",
        "injection",
        "deserializ",
        "unsafe",
        "encrypt",
        "decrypt",
        "cipher",
        "random.rand",
        "random.choice",
        "random.seed",
    }
)

# ---------------------------------------------------------------------------
# Dependency manifest file names (exact, case-insensitive).
# ---------------------------------------------------------------------------
_DEP_MANIFEST_NAMES: frozenset[str] = frozenset(
    {
        "requirements.txt",
        "requirements-dev.txt",
        "requirements_dev.txt",
        "requirements-test.txt",
        "requirements_test.txt",
        "pyproject.toml",
        "setup.cfg",
        "setup.py",
        "cargo.toml",
        "package.json",
        "package-lock.json",
        "yarn.lock",
        "gemfile",
        "gemfile.lock",
        "go.mod",
        "go.sum",
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
        "composer.json",
        "composer.lock",
    }
)

# Maximum source length to inspect (bytes).  Files larger than this are
# returned as None so the LLM handles them (they may contain complex patterns).
_MAX_SOURCE_BYTES = 512 * 1024  # 512 KB

# Minimum import count to consider a file "active" (non-trivial).
_MIN_IMPORT_LINES = 1

# Regex for Python import detection.
_IMPORT_RE = re.compile(r"^\s*(import |from \S+ import )", re.MULTILINE)


class StaticPreFilter:
    """
    Fast, deterministic file classifier for the LLM classification pre-gate.

    All methods are static so the class can be used without instantiation,
    matching the usage pattern in ``LLMClassificationPhase.classify_batch_async``.
    """

    @staticmethod
    def classify(file_path: str, source: str) -> dict[str, Any] | None:
        """
        Attempt to classify a file without an LLM call.

        Returns a classification dict compatible with the LLM phase output when
        a definitive decision can be made, or ``None`` when the file requires
        LLM analysis.

        The returned dict has the following shape::

            {
                "selected_frames": ["orphan"],   # or ["security", ...]
                "confidence": 0.95,
                "source": "static_prefilter",
                "reason": "human-readable explanation",
            }

        Args:
            file_path: Absolute or relative path to the source file.
            reason: Raw source text of the file.

        Returns:
            Classification dict, or None if LLM should handle this file.
        """
        if len(source) > _MAX_SOURCE_BYTES:
            logger.debug("static_prefilter_skip_large_file", path=file_path, size=len(source))
            return None

        path_obj = Path(file_path)
        filename = path_obj.name.lower()
        parts = [p.lower() for p in path_obj.parts]

        # ── Rule 1: Dependency manifests ─────────────────────────────────
        if filename in _DEP_MANIFEST_NAMES:
            logger.debug("static_prefilter_hit_dep_manifest", path=file_path)
            return {
                "selected_frames": ["deps"],
                "confidence": 0.97,
                "source": "static_prefilter",
                "reason": "Dependency manifest file — only deps frame applicable.",
            }

        # ── Rule 2: Test files ────────────────────────────────────────────
        # Files named test_*.py or *_test.py, or inside a tests/ directory.
        is_test_file = (
            filename.startswith("test_")
            or filename.endswith("_test.py")
            or filename.endswith("_spec.py")
            or "_test." in filename
            or "tests" in parts
            or "test" in parts
            or "__tests__" in parts
            or "spec" in parts
        )
        if is_test_file:
            logger.debug("static_prefilter_hit_test_file", path=file_path)
            return {
                "selected_frames": ["orphan"],
                "confidence": 0.90,
                "source": "static_prefilter",
                "reason": "Test file — security frame suppressed to avoid false positives.",
            }

        # ── Rule 3: Tiny files with no imports ───────────────────────────
        # Files under 20 lines with no imports are almost certainly stubs,
        # config snippets, or __init__.py placeholders.
        line_count = source.count("\n") + 1
        import_count = len(_IMPORT_RE.findall(source))
        if line_count < 20 and import_count == 0:
            logger.debug("static_prefilter_hit_tiny_no_imports", path=file_path, lines=line_count)
            return {
                "selected_frames": ["orphan"],
                "confidence": 0.88,
                "source": "static_prefilter",
                "reason": f"Tiny file ({line_count} lines, no imports) — orphan check only.",
            }

        # ── Rule 4: Security keyword presence ────────────────────────────
        # If any security-sensitive keyword appears, include the security frame.
        source_lower = source.lower()
        matched_keywords = [kw for kw in _SECURITY_KEYWORDS if kw in source_lower]
        if matched_keywords:
            logger.debug(
                "static_prefilter_hit_security_keywords",
                path=file_path,
                keywords=matched_keywords[:5],
            )
            # Return a result that includes security; caller may add more frames
            # via their own rule-based selection for resilience/orphan.
            return {
                "selected_frames": ["security", "resilience", "orphan"],
                "confidence": 0.80,
                "source": "static_prefilter",
                "reason": f"Security keywords found: {', '.join(matched_keywords[:3])}.",
                "matched_keywords": matched_keywords,
            }

        # ── No definitive classification ─────────────────────────────────
        return None

    @staticmethod
    def batch_classify(
        files: list[str],
        file_sources: dict[str, str],
    ) -> tuple[dict[str, dict[str, Any]], list[str]]:
        """
        Classify a batch of files, returning pre-classified results and
        the remaining files that require LLM classification.

        Args:
            files: Ordered list of file paths to classify.
            file_sources: Mapping of file_path -> source text.

        Returns:
            A 2-tuple:
            - ``pre_classified``: dict mapping file_path -> classification dict
              for files that were resolved without the LLM.
            - ``llm_needed``: list of file_paths that require LLM analysis.
        """
        pre_classified: dict[str, dict[str, Any]] = {}
        llm_needed: list[str] = []

        for file_path in files:
            source = file_sources.get(file_path, "")
            result = StaticPreFilter.classify(file_path, source)
            if result is not None:
                pre_classified[file_path] = result
            else:
                llm_needed.append(file_path)

        hit_count = len(pre_classified)
        total = len(files)
        hit_rate = hit_count / total if total else 0.0
        logger.info(
            "static_prefilter_hit",
            static_hits=hit_count,
            llm_needed=len(llm_needed),
            total=total,
            hit_rate_pct=round(hit_rate * 100, 1),
        )
        return pre_classified, llm_needed
