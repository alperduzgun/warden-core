"""
Resilience Architecture Analysis Frame

Tests code resilience, fault tolerance, and graceful degradation using LLM-based FMEA.

Usage:
    from . import ResilienceFrame

    frame = ResilienceFrame()
    result = await frame.execute_async(code_file)
"""

from ..resilience_frame import ResilienceFrame

__all__ = ["ResilienceFrame"]
