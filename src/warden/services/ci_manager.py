"""
CI Manager Service (Backward Compatibility Wrapper)

This module re-exports everything from the refactored ci_manager package
to maintain backward compatibility with existing imports.

New structure:
- ci_manager/manager.py: Main CIManager class
- ci_manager/provider_detection.py: Provider and branch detection
- ci_manager/template_operations.py: Template loading and processing
- ci_manager/file_operations.py: Atomic file operations
- ci_manager/validation.py: Input validation and security
- ci_manager/workflow_definitions.py: Workflow templates and data classes
- ci_manager/exceptions.py: Custom exceptions

Public API (unchanged):
    from warden.services.ci_manager import (
        CIManager,
        CIProvider,
        CIManagerError,
        ValidationError,
        SecurityError,
        TemplateError,
        FileOperationError,
        WorkflowTemplate,
        WorkflowStatus,
        CIStatus,
        WorkflowType,
        CURRENT_TEMPLATE_VERSION,
    )
"""

# Re-export everything from the refactored package
from warden.services.ci_manager.exceptions import (
    CIManagerError,
    FileOperationError,
    SecurityError,
    TemplateError,
    ValidationError,
)
from warden.services.ci_manager.manager import CIManager
from warden.services.ci_manager.provider_detection import CIProvider
from warden.services.ci_manager.template_operations import CURRENT_TEMPLATE_VERSION
from warden.services.ci_manager.workflow_definitions import (
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
