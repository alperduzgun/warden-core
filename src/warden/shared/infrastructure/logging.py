"""
Structured logging configuration using structlog.

Provides consistent, structured logging across all modules.

Issue #25 Fix: Privacy-aware logging with redaction support
"""

import logging
import re
import sys
from typing import Any, Dict

import structlog

from warden.shared.infrastructure.config import settings


def privacy_redactor(logger: Any, method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """
    Redact sensitive information from logs (Issue #25).

    Redacts:
    - Email addresses
    - IP addresses
    - File paths containing home directories
    - API keys
    - Passwords
    - Tokens

    Args:
        logger: Logger instance
        method_name: Logging method name
        event_dict: Event dictionary to process

    Returns:
        Redacted event dictionary
    """
    # Only redact if redaction is enabled
    if not getattr(settings, "log_redaction_enabled", True):
        return event_dict

    # Patterns to redact
    patterns = {
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b": "[EMAIL_REDACTED]",
        r"\b(?:\d{1,3}\.){3}\d{1,3}\b": "[IP_REDACTED]",
        r"/Users/[^/\s]+": "[HOME_REDACTED]",
        r"/home/[^/\s]+": "[HOME_REDACTED]",
        r"(api[_-]?key|token|password|secret)['\"]?\s*[:=]\s*['\"]?([^'\"\s]+)": r"\1=[REDACTED]",
        r"Bearer\s+\S+": "Bearer [TOKEN_REDACTED]",
    }

    def redact_string(text: str) -> str:
        """Redact sensitive patterns from a string."""
        for pattern, replacement in patterns.items():
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
        return text

    # Recursively redact all string values
    def redact_dict(d: dict) -> dict:
        """Recursively redact dictionary values."""
        return {
            k: (
                redact_string(v) if isinstance(v, str)
                else redact_dict(v) if isinstance(v, dict)
                else [redact_string(i) if isinstance(i, str) else i for i in v] if isinstance(v, list)
                else v
            )
            for k, v in d.items()
        }

    return redact_dict(event_dict)


def configure_logging(stream: Any = sys.stderr) -> None:
    """
    Configure structlog for the application.

    Sets up:
    - JSON output for production
    - Pretty console output for development
    - Log level from settings
    - Correlation ID support
    """
    # Determine if we want colored output
    use_colors = settings.is_development

    # Shared processors (including privacy redaction)
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        privacy_redactor,  # Issue #25: Redact sensitive info
    ]

    # Development: Pretty console output
    if settings.is_development:
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer(colors=use_colors),
        ]
    # Production: JSON output
    else:
        processors = shared_processors + [
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ]

    # Configure structlog
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        stream=stream,
        level=getattr(logging, settings.log_level.upper()),
        force=True, # Force reconfiguration in case it was already set
    )


def get_logger(name: str) -> Any:
    """
    Get a structured logger instance.

    Args:
        name: Logger name (typically __name__)

    Returns:
        Structured logger instance

    Example:
        >>> logger = get_logger(__name__)
        >>> logger.info("user_created", user_id="123", email="test@example.com")
    """
    return structlog.get_logger(name)
