"""Error classification using pattern matching."""

from __future__ import annotations

import re

from warden.self_healing.models import ErrorCategory

# Patterns indicating timeout errors
TIMEOUT_PATTERNS = [
    "timed out",
    "TimeoutError",
    "asyncio.TimeoutError",
    "deadline exceeded",
    "connection timed out",
    "read timed out",
]

# Patterns indicating external service errors
EXTERNAL_SERVICE_PATTERNS = [
    "ConnectionRefusedError",
    "ConnectionError",
    "HTTPError",
    "APIError",
    "ServiceUnavailable",
    "rate limit",
    "quota exceeded",
    "401 Unauthorized",
    "403 Forbidden",
    "500 Internal Server Error",
    "502 Bad Gateway",
    "503 Service Unavailable",
]

# Patterns indicating config errors
CONFIG_PATTERNS = [
    "invalid config",
    "configuration error",
    "missing key",
    "yaml.scanner",
    "yaml.parser",
    "toml.decoder",
    "invalid value for",
    "KeyError",
]

# Patterns indicating provider unavailability (distinct from external service)
PROVIDER_UNAVAILABLE_PATTERNS = [
    "provider.*unavailable",
    "no.*provider.*configured",
    "all.*providers.*failed",
    "provider.*not.*found",
]

# Pattern to extract module name from ImportError messages
IMPORT_PATTERNS = [
    re.compile(r"No module named ['\"]?([a-zA-Z0-9_]+(?:\.[a-zA-Z0-9_]+)*)['\"]?"),
    re.compile(r"cannot import name ['\"]?(\w+)['\"]? from ['\"]?([a-zA-Z0-9_.]+)['\"]?"),
    re.compile(r"ModuleNotFoundError: No module named ['\"]?([a-zA-Z0-9_]+)['\"]?"),
]


class ErrorClassifier:
    """Classifies exceptions into ErrorCategory using pattern matching."""

    def classify(self, error: Exception) -> ErrorCategory:
        """Pattern-match error type to category."""
        # Type-based classification first
        if isinstance(error, ModuleNotFoundError):
            return ErrorCategory.MODULE_NOT_FOUND
        if isinstance(error, ImportError):
            return ErrorCategory.IMPORT_ERROR
        if isinstance(error, PermissionError):
            return ErrorCategory.PERMISSION_ERROR

        # ModelNotFoundError detection (import-free)
        if type(error).__name__ == "ModelNotFoundError":
            return ErrorCategory.MODEL_NOT_FOUND

        error_str = str(error)
        error_type = type(error).__name__

        # Check timeout patterns
        for pattern in TIMEOUT_PATTERNS:
            if pattern.lower() in error_str.lower() or pattern in error_type:
                return ErrorCategory.TIMEOUT

        # Check provider unavailable patterns (before external service)
        for pattern in PROVIDER_UNAVAILABLE_PATTERNS:
            if re.search(pattern, error_str, re.IGNORECASE):
                return ErrorCategory.PROVIDER_UNAVAILABLE

        # Check external service patterns
        for pattern in EXTERNAL_SERVICE_PATTERNS:
            if pattern.lower() in error_str.lower() or pattern in error_type:
                return ErrorCategory.EXTERNAL_SERVICE

        # Check config patterns
        for pattern in CONFIG_PATTERNS:
            if pattern.lower() in error_str.lower():
                return ErrorCategory.CONFIG_ERROR

        return ErrorCategory.UNKNOWN

    @staticmethod
    def extract_module_name(error: Exception) -> str | None:
        """Extract module name from ImportError/ModuleNotFoundError message."""
        error_msg = str(error)
        for pattern in IMPORT_PATTERNS:
            match = pattern.search(error_msg)
            if match:
                module = match.group(1)
                return module.split(".")[0]
        return None
