"""
Anti-Pattern Detection Frame

Detects common Python anti-patterns using AST analysis:
- Bare except clauses
- God classes (500+ lines)
- Thread-unsafe singleton patterns
- Generic exception raising
- Debug print statements
- TODO/FIXME comments
- Built-in name shadowing
- Missing await on coroutines

This frame works on ANY Python project.

Usage:
    from warden.validation.frames.antipattern import AntiPatternFrame

    frame = AntiPatternFrame()
    result = await frame.execute_async(code_file)
"""

from warden.validation.frames.antipattern.antipattern_frame import AntiPatternFrame

__all__ = ["AntiPatternFrame"]
