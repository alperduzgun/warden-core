"""
CI Manager Exceptions

Custom exceptions for CI Manager errors.
"""


class CIManagerError(Exception):
    """Base exception for CI Manager errors."""
    pass


class ValidationError(CIManagerError):
    """Input validation failed."""
    pass


class SecurityError(CIManagerError):
    """Security violation detected."""
    pass


class TemplateError(CIManagerError):
    """Template loading or processing failed."""
    pass


class FileOperationError(CIManagerError):
    """File system operation failed."""
    pass
