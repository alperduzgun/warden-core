"""Git blame + churn-based risk weighting for findings prioritization.

After scan findings are collected, re-ranks them by combining base severity
with git churn data (commit frequency) and recency (last modified). High-churn
+ recently-modified files receive elevated priority.
"""

import subprocess
from math import log1p
from pathlib import Path
from typing import Any

from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)

# Severity scores for composite scoring
SEVERITY_SCORES: dict[str, float] = {
    "critical": 4.0,
    "high": 3.0,
    "medium": 2.0,
    "low": 1.0,
}

# Churn weight multiplier: composite = severity * (1 + log1p(churn) * CHURN_WEIGHT)
CHURN_WEIGHT: float = 0.2

# Git subprocess timeout in seconds
GIT_TIMEOUT: int = 10


class GitRiskWeighter:
    """Re-ranks findings using git churn data and severity composite scoring.

    Findings in frequently-modified files (high churn) are elevated in priority,
    reflecting the increased risk of regression and exposure in actively worked code.
    """

    def __init__(self, project_root: Path) -> None:
        """Initialize the weighter for a specific project root.

        Args:
            project_root: Absolute path to the project root directory.
        """
        self.project_root = Path(project_root).resolve()
        self._churn_cache: dict[str, int] = {}
        self._git_available: bool | None = None

    def _check_git_available(self) -> bool:
        """Check once if git is available and the directory is a git repo."""
        if self._git_available is not None:
            return self._git_available

        try:
            result = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                capture_output=True,
                text=True,
                cwd=str(self.project_root),
                timeout=GIT_TIMEOUT,
            )
            self._git_available = result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            self._git_available = False

        if not self._git_available:
            logger.info("git_risk_weighter_git_unavailable", project_root=str(self.project_root))

        return self._git_available

    def get_file_churn(self, file_path: str, days: int = 90) -> int:
        """Count git commits touching a file in the last N days.

        Runs: git log --since="<days> days ago" --oneline -- <file>

        Args:
            file_path: Path to the file, relative or absolute.
            days: Look-back window in days (default 90).

        Returns:
            Number of commits touching the file. Returns 0 on any error
            (git unavailable, not a repo, file never committed, etc.).
        """
        if not self._check_git_available():
            return 0

        cache_key = f"{file_path}:{days}"
        if cache_key in self._churn_cache:
            return self._churn_cache[cache_key]

        try:
            # Normalize to relative path inside the repo
            abs_path = Path(file_path)
            if not abs_path.is_absolute():
                abs_path = self.project_root / file_path

            try:
                rel_path = str(abs_path.resolve().relative_to(self.project_root))
            except ValueError:
                rel_path = str(file_path)

            result = subprocess.run(
                [
                    "git",
                    "log",
                    f"--since={days} days ago",
                    "--oneline",
                    "--",
                    rel_path,
                ],
                capture_output=True,
                text=True,
                cwd=str(self.project_root),
                timeout=GIT_TIMEOUT,
            )

            if result.returncode != 0:
                churn = 0
            else:
                churn = len([line for line in result.stdout.splitlines() if line.strip()])

        except (subprocess.TimeoutExpired, FileNotFoundError, OSError, Exception):
            churn = 0

        self._churn_cache[cache_key] = churn
        return churn

    def _get_severity_score(self, finding: Any) -> float:
        """Extract severity and return its numeric score."""
        if isinstance(finding, dict):
            severity = str(finding.get("severity", "medium")).lower()
        else:
            severity = str(getattr(finding, "severity", "medium")).lower()

        return SEVERITY_SCORES.get(severity, SEVERITY_SCORES["medium"])

    def _get_file_path(self, finding: Any) -> str:
        """Extract file path from a finding object or dict."""
        if isinstance(finding, dict):
            # Try common dict key names
            for key in ("file_path", "path", "location"):
                val = finding.get(key, "")
                if val:
                    # location may be "path:line" — extract path portion
                    if key == "location" and ":" in val:
                        return val.rsplit(":", 1)[0]
                    return str(val)
        else:
            for attr in ("file_path", "path"):
                val = getattr(finding, attr, None)
                if val:
                    return str(val)
            # Fall back to location attribute
            loc = getattr(finding, "location", "") or ""
            if loc and ":" in loc:
                return loc.rsplit(":", 1)[0]

        return ""

    def _composite_score(self, finding: Any) -> float:
        """Compute composite priority score for a finding.

        Formula: severity_score * (1 + log1p(churn) * CHURN_WEIGHT)

        Higher score = higher priority (sorted descending).
        """
        severity_score = self._get_severity_score(finding)
        file_path = self._get_file_path(finding)

        if file_path:
            churn = self.get_file_churn(file_path)
        else:
            churn = 0

        return severity_score * (1.0 + log1p(churn) * CHURN_WEIGHT)

    def weight_findings(self, findings: list[Any], project_root: Path | None = None) -> list[Any]:
        """Re-sort findings by composite risk score (severity x churn).

        Does NOT modify finding objects. Returns a new list in descending
        priority order (highest risk first).

        Args:
            findings: List of finding dicts or Finding objects.
            project_root: Optional override for project root (ignored if already set).

        Returns:
            New list of the same findings in descending composite score order.
        """
        if not findings:
            return findings

        if project_root is not None and project_root != self.project_root:
            self.project_root = Path(project_root).resolve()
            # Reset caches when project root changes
            self._churn_cache = {}
            self._git_available = None

        try:
            weighted = sorted(findings, key=self._composite_score, reverse=True)
            logger.info(
                "git_risk_weighting_applied",
                total_findings=len(findings),
                git_available=self._git_available,
            )
            return weighted
        except Exception as exc:
            logger.warning("git_risk_weighting_failed", error=str(exc))
            return findings
