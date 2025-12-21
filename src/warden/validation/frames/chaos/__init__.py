"""
Chaos Engineering Frame

Tests code resilience under failure conditions:
- Network failures and timeouts
- Service unavailability
- Race conditions
- Error handling

Components:
- ChaosFrame: Main frame
- Internal checks: circuit_breaker, error_handling, retry, timeout

Usage:
    from warden.validation.frames.chaos import ChaosFrame

    frame = ChaosFrame()
    result = await frame.execute(code_file)
"""

from warden.validation.frames.chaos.chaos_frame import ChaosFrame

__all__ = ["ChaosFrame"]
