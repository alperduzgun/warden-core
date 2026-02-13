"""
Shared ProjectIntelligence artifact.

Collected during PRE-ANALYSIS phase (AST only, no LLM calls).
Consumed by validation frames for context-aware analysis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProjectIntelligence:
    """
    Cross-cutting project intelligence gathered during pre-analysis.

    This artifact provides shared context to all validation frames,
    reducing redundant analysis and improving accuracy.

    Population: PRE-ANALYSIS phase (AST scanning only, zero LLM cost)
    Consumers: SecurityFrame, ArchitecturalFrame, and other validation frames
    """

    # Detected entry points and input sources
    input_sources: list[dict[str, Any]] = field(default_factory=list)
    # e.g., [{"source": "request.args", "file": "app.py", "line": 10}]

    # Critical sinks (SQL, CMD, HTML, File)
    critical_sinks: list[dict[str, Any]] = field(default_factory=list)
    # e.g., [{"sink": "cursor.execute", "type": "SQL", "file": "db.py", "line": 25}]

    # Authentication/authorization patterns detected
    auth_patterns: list[dict[str, Any]] = field(default_factory=list)

    # Dependency information
    dependencies: list[str] = field(default_factory=list)

    # Framework detection
    detected_frameworks: list[str] = field(default_factory=list)

    # File type distribution
    file_types: dict[str, int] = field(default_factory=dict)
    # e.g., {"python": 45, "javascript": 12}

    # Entry point files (routers, handlers, main)
    entry_points: list[str] = field(default_factory=list)

    # Test file paths (for exclusion or context)
    test_files: list[str] = field(default_factory=list)

    # Configuration files detected
    config_files: list[str] = field(default_factory=list)

    # Project-level metadata
    total_files: int = 0
    total_lines: int = 0
    primary_language: str = "unknown"

    def to_json(self) -> dict[str, Any]:
        """Serialize to JSON."""
        return {
            "input_sources": self.input_sources,
            "critical_sinks": self.critical_sinks,
            "auth_patterns": self.auth_patterns,
            "dependencies": self.dependencies,
            "detected_frameworks": self.detected_frameworks,
            "file_types": self.file_types,
            "entry_points": self.entry_points,
            "test_files": self.test_files,
            "config_files": self.config_files,
            "total_files": self.total_files,
            "total_lines": self.total_lines,
            "primary_language": self.primary_language,
        }

    @property
    def has_web_inputs(self) -> bool:
        """Check if project has web input sources."""
        web_patterns = {"request", "form", "params", "query", "body"}
        return any(any(p in str(s.get("source", "")).lower() for p in web_patterns) for s in self.input_sources)

    @property
    def has_sql_sinks(self) -> bool:
        """Check if project has SQL sinks."""
        return any(s.get("type") == "SQL" for s in self.critical_sinks)

    @property
    def has_cmd_sinks(self) -> bool:
        """Check if project has command execution sinks."""
        return any(s.get("type") == "CMD" for s in self.critical_sinks)
