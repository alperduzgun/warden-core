"""
Warden Fortification Module

This module provides code fortification capabilities to add safety measures
to AI-generated code. It includes:
- Error handling (try-except blocks)
- Logging integration (structlog)
- Input validation
- Resource disposal (context managers)
- Null/None checks

Architecture follows Python best practices and Panel JSON compatibility.
"""

from warden.fortification.fortifier import CodeFortifier
from warden.fortification.models import (
    FortificationResult,
    FortificationAction,
    FortificationActionType,
    FortifierPriority,
    FortificationSuggestion,
)
from warden.fortification.base import BaseFortifier

__all__ = [
    "CodeFortifier",
    "FortificationResult",
    "FortificationAction",
    "FortificationActionType",
    "FortifierPriority",
    "BaseFortifier",
]
