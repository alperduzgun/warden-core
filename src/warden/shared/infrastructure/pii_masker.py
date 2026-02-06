"""
PII Masking Filter for Logs (ID 25).

Prevents sensitive data from appearing in logs.
"""

import re
from typing import Any, Dict


class PIIMaskingFilter:
    """Mask PII/sensitive data in logs."""

    EMAIL_PATTERN = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')
    API_KEY_PATTERN = re.compile(r'(?i)(api[_-]?key|token|secret)[\s:=]+["\']?([a-zA-Z0-9_\-]{20,})["\']?')
    
    @classmethod
    def mask_message(cls, message: str) -> str:
        """Mask PII in string."""
        if not isinstance(message, str):
            return message
        message = cls.EMAIL_PATTERN.sub('[EMAIL]', message)
        message = cls.API_KEY_PATTERN.sub(r'\1=***', message)
        return message

    def __call__(self, event_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Structlog processor."""
        if 'event' in event_dict:
            event_dict['event'] = self.mask_message(str(event_dict['event']))
        return event_dict
