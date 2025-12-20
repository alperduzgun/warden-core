"""
Simple logger wrapper for compatibility.

Provides structlog-like interface with fallback to standard logging.
"""
import logging


class SimpleLogger:
    """Simple logger with keyword argument support."""

    def __init__(self, name: str):
        """Initialize logger."""
        self.logger = logging.getLogger(name)
        if not self.logger.handlers:
            logging.basicConfig(
                level=logging.INFO,
                format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )

    def info(self, message: str, **kwargs):
        """Log info message."""
        extra_info = " ".join(f"{k}={v}" for k, v in kwargs.items())
        full_message = f"{message} {extra_info}" if kwargs else message
        self.logger.info(full_message)

    def warning(self, message: str, **kwargs):
        """Log warning message."""
        extra_info = " ".join(f"{k}={v}" for k, v in kwargs.items())
        full_message = f"{message} {extra_info}" if kwargs else message
        self.logger.warning(full_message)

    def error(self, message: str, **kwargs):
        """Log error message."""
        extra_info = " ".join(f"{k}={v}" for k, v in kwargs.items())
        full_message = f"{message} {extra_info}" if kwargs else message
        self.logger.error(full_message)

    def debug(self, message: str, **kwargs):
        """Log debug message."""
        extra_info = " ".join(f"{k}={v}" for k, v in kwargs.items())
        full_message = f"{message} {extra_info}" if kwargs else message
        self.logger.debug(full_message)


def get_logger(name: str = None) -> SimpleLogger:
    """Get logger instance."""
    return SimpleLogger(name or __name__)
