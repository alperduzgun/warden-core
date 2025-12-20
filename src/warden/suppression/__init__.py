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
from warden.suppression.matcher import SuppressionMatcher
from warden.suppression.config_loader import (
    load_suppression_config,
    save_suppression_config,
    create_default_config,
)

__all__ = [
    'SuppressionType',
    'SuppressionEntry',
    'SuppressionConfig',
    'SuppressionMatcher',
    'load_suppression_config',
    'save_suppression_config',
    'create_default_config',
]
