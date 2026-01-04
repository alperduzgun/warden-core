"""Enums for custom rules system.

This module defines enumerations for rule categories and severities.
All enum values MUST match Panel TypeScript types exactly.
"""

from enum import Enum


class RuleCategory(Enum):
    """Category of custom rule.

    Must match Panel TypeScript: 'security' | 'convention' | 'performance' | 'custom'
    """

    SECURITY = "security"
    CONVENTION = "convention"
    PERFORMANCE = "performance"
    CUSTOM = "custom"


class RuleSeverity(Enum):
    """Severity level of rule violation.

    Must match Panel TypeScript: 'critical' | 'high' | 'medium' | 'low'
    """

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class RuleType(Enum):
    """Type of custom rule execution logic.
    
    Determines how the rule is evaluated.
    """
    
    SECURITY = "security"
    CONVENTION = "convention" 
    PATTERN = "pattern"
    SCRIPT = "script"
