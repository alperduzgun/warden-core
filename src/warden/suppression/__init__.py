"""
Suppression module for handling false positives in Warden.

This module provides functionality to suppress issues using:
- Inline comments (# warden-ignore, // warden-ignore)
- Configuration files (.warden/suppressions.yaml)
- Global suppressions

Exports:
    - SuppressionType: Enum for suppression types
    - SuppressionEntry: Individual suppression entry
    - SuppressionConfig: Configuration model
    - SuppressionMatcher: Main suppression matching logic
    - load_suppression_config: Load configuration from file
"""

from warden.suppression.models import (
    SuppressionType,
    SuppressionEntry,
    SuppressionConfig,
)

__all__ = [
    'SuppressionType',
    'SuppressionEntry',
    'SuppressionConfig',
]
