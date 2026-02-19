"""Re-export taint domain types from their canonical location.

The original types live in ``security/_internal/`` and stay there for backward
compatibility.  This module provides a clean import path for consumers outside
the security frame.
"""

from __future__ import annotations

from warden.validation.frames.security._internal.taint_analyzer import (
    TAINT_DEFAULTS,
    TaintAnalyzer,
    TaintPath,
    TaintSink,
    TaintSource,
    validate_taint_config,
)
from warden.validation.frames.security._internal.taint_catalog import TaintCatalog

__all__ = [
    "TAINT_DEFAULTS",
    "TaintAnalyzer",
    "TaintCatalog",
    "TaintPath",
    "TaintSink",
    "TaintSource",
    "validate_taint_config",
]
