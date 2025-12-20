"""
Base exceptions for Warden application.

All custom exceptions should inherit from WardenException.
"""

from typing import Any, Dict


class WardenException(Exception):
    """Base exception for all Warden errors."""

    def __init__(self, message: str, details: Dict[str, Any] | None = None) -> None:
        """
        Initialize exception.

        Args:
            message: Human-readable error message
            details: Additional error context for logging
        """
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ValidationError(WardenException):
    """Raised when input validation fails."""

    pass


class NotFoundError(WardenException):
    """Raised when a resource is not found."""

    pass


class AlreadyExistsError(WardenException):
    """Raised when trying to create a resource that already exists."""

    pass


class ConfigurationError(WardenException):
    """Raised when configuration is invalid or missing."""

    pass


class ExternalServiceError(WardenException):
    """Raised when an external service (Qdrant, LLM, etc.) fails."""

    pass


class SecurityError(WardenException):
    """Raised when security validation fails (path traversal, injection, etc.)."""

    pass


class PersistenceError(WardenException):
    """Raised when file or database operations fail."""

    pass
