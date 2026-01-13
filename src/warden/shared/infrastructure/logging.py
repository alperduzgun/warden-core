"""
Structured logging configuration using structlog.

Provides consistent, structured logging across all modules.
"""

import logging
import sys
from typing import Any

import structlog

from warden.shared.infrastructure.config import settings


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

    # Shared processors
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
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
