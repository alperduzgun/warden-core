"""
Domain exceptions for Warden.

Follows the "Fail Fast" and "Strict Types" principles.
All application errors should inherit from WardenError.
"""


class WardenError(Exception):
    """Base class for all Warden exceptions."""

    def __init__(self, message: str, context: dict = None):
        super().__init__(message)
        self.context = context or {}


class ResilienceError(WardenError):
    """Raised when self-healing mechanisms fail."""

    pass


class SecurityViolation(WardenError):
    """Raised when a security constraint is violated (e.g. path traversal)."""

    pass


class InstallError(WardenError):
    """Raised when installation fails (non-idempotent or broken)."""

    pass


class ConfigurationError(WardenError):
    """Raised when configuration is invalid or corrupt."""

    pass


class ReportError(WardenError):
    """Raised when report generation fails."""

    pass
