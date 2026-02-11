"""
CI Manager Service

Central service for managing CI/CD workflow files.
Provides init, update, sync, and status operations for CI workflows.

Public API (re-exported for backward compatibility):
- CIManager: Main manager class
- CIProvider: Enum of supported CI providers
- Exceptions: CIManagerError, ValidationError, SecurityError, TemplateError, FileOperationError
- Data classes: WorkflowTemplate, WorkflowStatus, CIStatus, WorkflowType
- Constants: CURRENT_TEMPLATE_VERSION
"""

from .exceptions import (
    CIManagerError,
    FileOperationError,
    SecurityError,
    TemplateError,
    ValidationError,
)
from .manager import CIManager
from .provider_detection import CIProvider
from .template_operations import CURRENT_TEMPLATE_VERSION
from .workflow_definitions import (
    CIStatus,
    WorkflowStatus,
    WorkflowTemplate,
    WorkflowType,
)

__all__ = [
    # Main class
    "CIManager",
    # Enums
    "CIProvider",
    "WorkflowType",
    # Data classes
    "WorkflowTemplate",
    "WorkflowStatus",
    "CIStatus",
    # Exceptions
    "CIManagerError",
    "ValidationError",
    "SecurityError",
    "TemplateError",
    "FileOperationError",
    # Constants
    "CURRENT_TEMPLATE_VERSION",
]
