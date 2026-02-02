"""
Utilities for safely interacting with Finding objects and dictionaries.
Ensures resilience across different data representations in the pipeline.
"""

from typing import Any, Dict, Union

def get_finding_attribute(finding: Union[Any, Dict[str, Any]], attr: str, default: Any = None) -> Any:
    """
    Safely retrieves an attribute from a Finding object or a dictionary.
    
    Args:
        finding: The finding object or dictionary.
        attr: The attribute/key name.
        default: Default value if not found.
        
    Returns:
        The value or default.
    """
    if finding is None:
        return default
        
    if isinstance(finding, dict):
        return finding.get(attr, default)
    
    return getattr(finding, attr, default)

def set_finding_attribute(finding: Union[Any, Dict[str, Any]], attr: str, value: Any) -> None:
    """
    Safely sets an attribute on a Finding object or a dictionary.
    """
    if finding is None:
        return
        
    if isinstance(finding, dict):
        finding[attr] = value
    else:
        setattr(finding, attr, value)

def get_finding_severity(finding: Union[Any, Dict[str, Any]]) -> str:
    """Safely gets normalized severity."""
    sev = get_finding_attribute(finding, 'severity', 'medium')
    return str(sev).lower() if sev else 'medium'
