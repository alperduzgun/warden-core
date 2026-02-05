"""
Anti-Pattern Detection Frame (Universal AST)

Detects common anti-patterns across 50+ programming languages using Universal AST.

Supported Languages (via Tree-sitter):
- Python, JavaScript, TypeScript, Java, C#, Go, Rust, Ruby, PHP
- Kotlin, Swift, Scala, Dart, C, C++, and 35+ more

Detections:
- Empty/bare catch blocks (exception swallowing)
- God classes (500+ lines)
- Debug output in production
- TODO/FIXME comments
- Generic exception throwing

Architecture:
1. ASTProviderRegistry -> Best provider for language
2. Universal AST queries -> Language-agnostic detection
3. Regex fallback -> When AST unavailable

Usage:
    from warden.validation.frames.antipattern import AntiPatternFrame

    frame = AntiPatternFrame()
    result = await frame.execute_async(code_file)
"""

from warden.validation.frames.antipattern.antipattern_frame import (
    AntiPatternFrame,
    AntiPatternSeverity,
    AntiPatternViolation,
)

__all__ = ["AntiPatternFrame", "AntiPatternSeverity", "AntiPatternViolation"]
