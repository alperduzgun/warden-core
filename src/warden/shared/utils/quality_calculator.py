"""
Quality Score Calculator.

Centralizes the logic for calculating the project's quality/resilience score based on findings.
"""

from typing import Any


def calculate_quality_score(findings: list[Any], base_score: float = 10.0) -> float:
    """
    Calculate quality score using asymptotic decay formula.

    Formula: Base * (20 / (Penalty + 20))
    This ensures the score never hits absolute zero and scales well with finding count.

    Penalties:
    - Critical: 3.0
    - High: 1.5
    - Medium: 0.5
    - Low: 0.1

    Args:
        findings: List of Finding objects or dicts.
        base_score: Starting score (default 10.0)

    Returns:
        Float score between 0.1 and 10.0.
    """
    if not findings:
        return base_score

    from warden.shared.utils.finding_utils import get_finding_severity

    critical = sum(1 for f in findings if get_finding_severity(f) == "critical")
    high = sum(1 for f in findings if get_finding_severity(f) == "high")
    medium = sum(1 for f in findings if get_finding_severity(f) == "medium")
    low = sum(1 for f in findings if get_finding_severity(f) == "low")

    penalty = (critical * 3.0) + (high * 1.5) + (medium * 0.5) + (low * 0.1)

    # Asymptotic decay formula
    score = base_score * (20.0 / (penalty + 20.0))

    # Cap result within bounds
    return max(0.1, min(base_score, score))


def get_shield_data(findings: list[Any], base_score: float = 10.0) -> dict:
    """
    Generate Shields.io endpoint JSON data for the project quality.

    Args:
        findings: List of finding objects
        base_score: Initial score (default 10.0)

    Returns:
        Dict matching Shields.io endpoint schema:
        {
            "schemaVersion": 1,
            "label": "Warden Quality",
            "message": "9.5 / 10",
            "color": "brightgreen"
        }
    """
    score = calculate_quality_score(findings, base_score)

    # Determine color based on score thresholds
    if score >= 9.0:
        color = "brightgreen"
    elif score >= 7.5:
        color = "green"
    elif score >= 5.0:
        color = "yellow"
    elif score >= 2.5:
        color = "orange"
    else:
        color = "red"

    return {
        "schemaVersion": 1,
        "label": "Warden Quality",
        "message": f"{score:.1f} / 10",
        "color": color,
        "namedLogo": "shields.io",  # Optional styling
        "style": "flat",
    }


def calculate_base_score(linter_metrics: dict[str, Any] | None = None) -> float:
    """
    Calculate an objective baseline score (0.1 - 10.0) from structural/linter metrics.

    Uses the same asymptotic decay formula as ``calculate_quality_score``
    so scores are on a consistent scale.

    Args:
        linter_metrics: Dictionary of LinterResult objects or dicts keyed by tool name.

    Returns:
        Float base score clamped to [0.1, 10.0].  Returns 10.0 when no metrics available.
    """
    if not linter_metrics:
        return 10.0

    penalty = 0.0
    for _tool, metrics in linter_metrics.items():
        # Guard: handle both LinterResult objects and plain dicts
        is_available = getattr(metrics, "is_available", False) or (
            isinstance(metrics, dict) and metrics.get("is_available")
        )
        if not is_available:
            continue

        if isinstance(metrics, dict):
            blocker_count = metrics.get("blocker_count", 0)
            total_errors = metrics.get("total_errors", 0)
        else:
            blocker_count = getattr(metrics, "blocker_count", 0)
            total_errors = getattr(metrics, "total_errors", 0)

        penalty += (blocker_count * 0.5) + (total_errors * 0.05)

    score = 10.0 * (20.0 / (penalty + 20.0))
    return round(max(0.1, min(10.0, score)), 1)
