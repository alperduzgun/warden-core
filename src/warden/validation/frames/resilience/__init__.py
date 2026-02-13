"""
Chaos Engineering Analysis Frame

Applies chaos engineering principles to code:
- Detects external dependencies (network, DB, files, queues, cloud)
- LLM simulates failure scenarios (timeout, error, resource exhaustion)
- Reports MISSING resilience patterns (not validates existing ones)

Philosophy: "Everything will fail. The question is HOW and WHEN."

Usage:
    from . import ResilienceFrame

    frame = ResilienceFrame()
    result = await frame.execute_async(code_file)
"""

from warden.validation.frames.resilience.resilience_frame import ResilienceFrame

__all__ = ["ResilienceFrame"]
