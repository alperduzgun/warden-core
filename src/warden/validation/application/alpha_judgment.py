"""
Alpha Judgment: High-Speed Heuristic Filtering.

This module implements the "Alpha Judgment" layer which filters out obvious false positives
from the Rust Validation Engine before they reach the expensive LLM analysis stage.

Logic:
1. Context Awareness: Secrets in comments are likely false positives.
2. Density Check: Files with too many "secrets" are likely test data or config maps.
3. Entropy/Format: (Future) Check if the secret looks random enough.
"""

import os
from typing import Any, Dict, List

from warden.shared.infrastructure.logging import get_logger
from warden.validation.domain.frame import CodeFile, Finding

logger = get_logger(__name__)


class AlphaJudgment:
    """
    Alpha Judgment engine for pre-LLM filtering.
    """

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        # Configuration defaults
        self.max_findings_per_file = self.config.get("max_findings_per_file", 50)
        self.filter_comments = self.config.get("filter_comments", True)
        self.comment_patterns = {
            "python": ["#"],
            "javascript": ["//", "/*"],
            "typescript": ["//", "/*"],
            "java": ["//", "/*"],
            "c": ["//", "/*"],
            "cpp": ["//", "/*"],
            "rust": ["//", "/*"],
            "go": ["//", "/*"],
            "yaml": ["#"],
            "yml": ["#"],
            "toml": ["#"],
            "sh": ["#"],
            "bash": ["#"],
            "zsh": ["#"],
        }

    def evaluate(self, findings: list[Finding], code_files: list[CodeFile]) -> list[Finding]:
        """
        Evaluate and filter findings based on heuristics.

        Args:
            findings: List of raw findings from Rust/Regex engine.
            code_files: List of code files (for content lookup).

        Returns:
            Filtered list of findings.
        """
        if not findings:
            return []

        start_count = len(findings)

        # 1. Map files for quick lookup
        file_map = {cf.path: cf for cf in code_files}

        # 2. Group findings by file for density check
        findings_by_file: dict[str, list[Finding]] = {}
        for f in findings:
            path = self._get_path_from_finding(f)
            if path:
                if path not in findings_by_file:
                    findings_by_file[path] = []
                findings_by_file[path].append(f)

        valid_findings = []
        ignored_density = 0
        ignored_comment = 0

        for path, file_findings in findings_by_file.items():
            # A. Density Check
            if len(file_findings) > self.max_findings_per_file:
                logger.debug(
                    "alpha_judgment_density_filtered",
                    file=path,
                    count=len(file_findings),
                    limit=self.max_findings_per_file,
                )
                ignored_density += len(file_findings)
                # Ideally, we might want to keep one "summary" finding,
                # but for noise reduction, we often drop them as "test data".
                # Optional: Add a single warning?
                continue

            code_file = file_map.get(os.path.abspath(path)) or file_map.get(path)

            # If we don't have file content, we can't do context checks, so keep them (fail open)
            if not code_file:
                valid_findings.extend(file_findings)
                continue

            # B. Context Check (Comments)
            for finding in file_findings:
                if self.filter_comments and self._is_in_comment(finding, code_file):
                    ignored_comment += 1
                    continue

                valid_findings.append(finding)

        logger.info(
            "alpha_judgment_complete",
            input=start_count,
            output=len(valid_findings),
            dropped_density=ignored_density,
            dropped_comment=ignored_comment,
        )

        return valid_findings

    def _get_path_from_finding(self, finding: Finding) -> str | None:
        """Extract path from finding location."""
        if hasattr(finding, "file_path") and finding.file_path:
            return finding.file_path
        if finding.location:
            return finding.location.split(":")[0]
        return None

    def _is_in_comment(self, finding: Finding, code_file: CodeFile) -> bool:
        """
        Check if the finding is within a comment line.

        Note: This is a fast heuristic, not a full AST check.
        It checks if the line containing the finding starts with a comment marker
        (ignoring whitespace).
        Multi-line comments are harder with just line number,
        so we focus on single-line markers for speed.
        """
        if finding.line <= 0:
            return False

        # Get line content
        lines = code_file.content.splitlines()
        if finding.line > len(lines):
            return False

        line_content = lines[finding.line - 1].strip()

        # Get language markers
        lang = code_file.language.lower() if code_file.language else "unknown"
        # Normalize language (e.g. python3 -> python)
        if "python" in lang:
            lang = "python"

        markers = self.comment_patterns.get(lang, [])

        for marker in markers:
            # Check if line starts with marker
            if line_content.startswith(marker):
                return True

            # Check if marker is BEFORE the match in the same line?
            # finding.column is 1-based start index.
            # If marker is present and its index is < finding.column,
            # then the finding is inside a comment (trailing comment).

            # Simple check: if marker exists in line, check position
            try:
                marker_idx = lines[finding.line - 1].find(marker)
                if marker_idx != -1:
                    # finding.column is 1-based, marker_idx is 0-based
                    # If match starts after the marker, it's commented out
                    if (finding.column - 1) > marker_idx:
                        return True
            except (ValueError, TypeError, KeyError):  # Judgment extraction
                pass

        return False
