"""
Chaos Engineering Frame

Injects random failures to test system resilience:
- Timeouts (simulated hangs)
- Exceptions (runtime errors)
- Malformed outputs (type violations)
- Resource exhaustion
- Partial failures

Usage:
    from . import ChaosFrame

    frame = ChaosFrame()
    result = await frame.execute(code_file)
"""

from warden.validation.frames.chaos.chaos_frame import ChaosFrame

__all__ = ["ChaosFrame"]
