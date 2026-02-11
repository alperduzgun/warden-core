"""
Security Analysis Frame

Detects security vulnerabilities:
- SQL injection
- XSS (Cross-Site Scripting)
- Hardcoded secrets (API keys, passwords)
- Command injection
- Path traversal

Components:
- SecurityFrame: Main frame
- Internal checks: hardcoded_password, secrets, sql_injection, xss

Usage:
    from . import SecurityFrame

    frame = SecurityFrame()
    result = await frame.execute(code_file)
"""

from ..security_frame import SecurityFrame

__all__ = ["SecurityFrame"]
