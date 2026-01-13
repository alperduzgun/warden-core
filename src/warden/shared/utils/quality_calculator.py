"""
Quality Score Calculator.

Centralizes the logic for calculating the project's quality/resilience score based on findings.
"""
from typing import List, Any, Union

def calculate_quality_score(findings: List[Any], base_score: float = 10.0) -> float:
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

    # Helper to safe-get severity
    def get_severity(f: Any) -> str:
        if isinstance(f, dict):
            return str(f.get('severity', '')).lower()
        return str(getattr(f, 'severity', '')).lower()

    critical = sum(1 for f in findings if get_severity(f) == 'critical')
    high = sum(1 for f in findings if get_severity(f) == 'high')
    medium = sum(1 for f in findings if get_severity(f) == 'medium')
    low = sum(1 for f in findings if get_severity(f) == 'low')

    penalty = (critical * 3.0) + (high * 1.5) + (medium * 0.5) + (low * 0.1)
    
    # Asymptotic decay formula
    score = base_score * (20.0 / (penalty + 20.0))
    
    # Cap result within bounds
    return max(0.1, min(base_score, score))
