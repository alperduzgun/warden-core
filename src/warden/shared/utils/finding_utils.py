"""
Utilities for safely interacting with Finding objects and dictionaries.
Ensures resilience across different data representations in the pipeline.
"""

from typing import Any, Dict, Union


def get_finding_attribute(finding: Any, attr: str, default: Any = None) -> Any:
    """
    Safely retrieves an attribute from a Finding object or a dictionary.
    Ensures that .get() is only called on objects that truly support it (like dicts).
    """
    if finding is None:
        return default

    # Strictly check for dict type to avoid calling .get() on Finding objects
    if isinstance(finding, dict):
        try:
            return finding.get(attr, default)
        except AttributeError:
            # Fallback for dict-like objects that might fail .get
            pass

    # Use getattr for everything else, which is safe for Finding objects
    return getattr(finding, attr, default)

def set_finding_attribute(finding: Any, attr: str, value: Any) -> None:
    """
    Safely sets an attribute on a Finding object or a dictionary.
    """
    if finding is None:
        return

    if isinstance(finding, dict):
        try:
            finding[attr] = value
            return
        except (TypeError, KeyError):
            pass

    # Fallback to setattr for objects
    try:
        setattr(finding, attr, value)
    except (AttributeError, TypeError):
        # Ignore if immutable or missing
        pass

def get_finding_severity(finding: Any) -> str:
    """Safely gets normalized severity."""
    sev = get_finding_attribute(finding, 'severity', 'medium')
    return str(sev).lower() if sev else 'medium'
