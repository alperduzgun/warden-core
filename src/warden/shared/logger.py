"""
Simple logger wrapper for compatibility.

Provides structlog-like interface with fallback to standard logging.
"""
import logging
import re

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

    def _scrub(self, text: str) -> str:
        """
        Scrub sensitive information from logs.
        
        Security: Masks API keys and large code blocks.
        Performance: Skips regex on very short strings.
        """
        if not text:
            return ""
        
        # Performance shortcut for short strings (unlikely to have 50-char code block or keys)
        if len(text) < 20:
             return text

        # Scrub source code (heuristics)
        # Defense in Depth: Limit max log length to avoid DoS via logs
        if len(text) > 10000:
            text = text[:10000] + "... [TRUNCATED]"

        if "def " in text or "class " in text or "async def " in text:
            if len(text) > 50: # Only mask if looking like a block
                return "[SOURCE CODE REDACTED]"
        
        # Scrub potential API keys (basic heuristic)
        if "key=" in text.lower() or "token=" in text.lower():
            text = re.sub(r'(key|token)=([a-zA-Z0-9_\-]+)', r'\1=[REDACTED]', text, flags=re.IGNORECASE)
            
        return text

    def _format(self, message: str, **kwargs) -> str:
        """Format message with scrubbed kwargs and message."""
        extra_info = " ".join(f"{k}={self._scrub(str(v))}" for k, v in kwargs.items())
        full_message = f"{message} {extra_info}" if kwargs else message
        return self._scrub(full_message)

    def info(self, message: str, **kwargs):
        """Log info message."""
        self.logger.info(self._format(message, **kwargs))

    def warning(self, message: str, **kwargs):
        """Log warning message."""
        self.logger.warning(self._format(message, **kwargs))

    def error(self, message: str, **kwargs):
        """Log error message."""
        self.logger.error(self._format(message, **kwargs))

    def debug(self, message: str, **kwargs):
        """Log debug message."""
        self.logger.debug(self._format(message, **kwargs))


def get_logger(name: str = None) -> SimpleLogger:
    """Get logger instance."""
    return SimpleLogger(name or __name__)
