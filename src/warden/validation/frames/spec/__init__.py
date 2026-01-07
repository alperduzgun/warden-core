"""
Warden Spec Frame - API Contract Extraction and Comparison.

This frame extracts API contracts from multiple platforms (frontend/backend)
and identifies gaps between what consumers expect and what providers offer.

Usage:
    Configure platforms in .warden/config.yaml:

    frames:
      spec:
        platforms:
          - name: mobile
            path: ../invoice-mobile
            type: flutter
            role: consumer
          - name: backend
            path: ../invoice-api
            type: spring
            role: provider
"""

from warden.validation.frames.spec.spec_frame import SpecFrame
from warden.validation.frames.spec.models import (
    Contract,
    OperationDefinition,
    ModelDefinition,
    EnumDefinition,
    FieldDefinition,
    PlatformConfig,
    PlatformType,
    PlatformRole,
    OperationType,
    ContractGap,
    GapSeverity,
    SpecAnalysisResult,
)

__all__ = [
    "SpecFrame",
    "Contract",
    "OperationDefinition",
    "ModelDefinition",
    "EnumDefinition",
    "FieldDefinition",
    "PlatformConfig",
    "PlatformType",
    "PlatformRole",
    "OperationType",
    "ContractGap",
    "GapSeverity",
    "SpecAnalysisResult",
]
