"""
File Context Model for PRE-ANALYSIS Phase.

Provides file-level context detection for false positive prevention
and context-aware weight adjustment.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path

from warden.shared.domain.base_model import BaseDomainModel


class FileContext(Enum):
    """
    Context type for a file.

    Determines how analysis rules and suppressions are applied.
    """

    PRODUCTION = "production"  # Real production code - strictest rules
    TEST = "test"  # Test files - relaxed security rules
    EXAMPLE = "example"  # Example/demo code - educational focus
    FRAMEWORK = "framework"  # Framework/library code - pattern definitions
    DOCUMENTATION = "doc"  # Documentation files - skip most checks
    CONFIGURATION = "config"  # Config files - specific validation
    GENERATED = "generated"  # Auto-generated code - limited analysis
    VENDOR = "vendor"  # Third-party code - usually skipped
    MIGRATION = "migration"  # Database migrations - specific rules
    FIXTURE = "fixture"  # Test fixtures/mock data - ignore security
    SCRIPT = "script"  # Utility scripts - relaxed rules
    UNKNOWN = "unknown"  # Cannot determine context


@dataclass
class ContextWeight(BaseDomainModel):
    """
    Weight configuration for a specific metric in a context.

    Adjusts how different quality metrics are weighted based on file context.
    """

    metric_name: str  # e.g., "complexity", "duplication"
    weight: float  # 0.0 to 1.0
    reason: str  # Why this weight was chosen

    def to_json(self) -> Dict[str, Any]:
        """Convert to Panel-compatible JSON."""
        return {
            "metricName": self.metric_name,
            "weight": self.weight,
            "reason": self.reason,
        }


@dataclass
class ContextWeights(BaseDomainModel):
    """
    Complete weight configuration for a file context.

    Defines how quality metrics are weighted for different file types.
    """

    context: FileContext
    weights: Dict[str, float] = field(default_factory=dict)
    # Default weights: complexity, duplication, maintainability, naming, documentation, testability

    def __post_init__(self) -> None:
        """Initialize with default weights if not provided."""
        if not self.weights:
            self.weights = self._get_default_weights()

    def _get_default_weights(self) -> Dict[str, float]:
        """Get default weights based on context."""
        # Context-specific weight configurations
        weight_configs = {
            FileContext.PRODUCTION: {
                "complexity": 0.25,
                "duplication": 0.20,
                "maintainability": 0.20,
                "naming": 0.15,
                "documentation": 0.15,
                "testability": 0.05,
            },
            FileContext.TEST: {
                "complexity": 0.10,  # Tests can be complex
                "duplication": 0.05,  # Test patterns often repeat
                "maintainability": 0.15,
                "naming": 0.10,
                "documentation": 0.05,  # Self-documenting tests
                "testability": 0.55,  # Test quality is key!
            },
            FileContext.EXAMPLE: {
                "complexity": 0.05,  # Must be simple to understand
                "duplication": 0.10,
                "maintainability": 0.10,
                "naming": 0.25,  # Clear naming critical
                "documentation": 0.40,  # Educational docs critical
                "testability": 0.10,
            },
            FileContext.FRAMEWORK: {
                "complexity": 0.20,
                "duplication": 0.15,
                "maintainability": 0.25,  # Framework code needs maintenance
                "naming": 0.20,
                "documentation": 0.15,
                "testability": 0.05,
            },
            FileContext.CONFIGURATION: {
                "complexity": 0.05,  # Config should be simple
                "duplication": 0.30,  # DRY is important in config
                "maintainability": 0.30,
                "naming": 0.20,
                "documentation": 0.10,
                "testability": 0.05,
            },
            FileContext.MIGRATION: {
                "complexity": 0.10,
                "duplication": 0.10,
                "maintainability": 0.20,
                "naming": 0.10,
                "documentation": 0.20,  # Migration docs important
                "testability": 0.30,  # Rollback testing critical
            },
            FileContext.SCRIPT: {
                "complexity": 0.15,
                "duplication": 0.15,
                "maintainability": 0.20,
                "naming": 0.15,
                "documentation": 0.25,  # Script usage docs
                "testability": 0.10,
            },
        }

        # Return specific weights or default production weights
        return weight_configs.get(
            self.context,
            weight_configs[FileContext.PRODUCTION]
        )

    def to_json(self) -> Dict[str, Any]:
        """Convert to Panel-compatible JSON."""
        return {
            "context": self.context.value,
            "weights": self.weights,
        }


@dataclass
class FileContextInfo(BaseDomainModel):
    """
    Complete context information for a file.

    Includes detected context, confidence, and suppression rules.
    """

    file_path: str
    context: FileContext
    confidence: float  # 0.0 to 1.0
    detection_method: str  # How context was detected
    weights: ContextWeights = field(default_factory=lambda: ContextWeights(FileContext.PRODUCTION))

    # Suppression configuration
    suppressed_issues: List[str] = field(default_factory=list)  # Issue types to suppress
    suppression_reason: Optional[str] = None

    # Additional metadata
    is_entry_point: bool = False  # Main file, app.py, index.js, etc.
    is_generated: bool = False  # Auto-generated file
    is_vendor: bool = False  # Third-party code
    has_ignore_marker: bool = False  # Has "warden-ignore" comment

    def to_json(self) -> Dict[str, Any]:
        """Convert to Panel-compatible JSON."""
        return {
            "filePath": self.file_path,
            "context": self.context.value,
            "confidence": round(self.confidence, 2),
            "detectionMethod": self.detection_method,
            "weights": self.weights.to_json(),
            "suppressedIssues": self.suppressed_issues,
            "suppressionReason": self.suppression_reason,
            "metadata": {
                "isEntryPoint": self.is_entry_point,
                "isGenerated": self.is_generated,
                "isVendor": self.is_vendor,
                "hasIgnoreMarker": self.has_ignore_marker,
            }
        }

    def should_suppress_issue(self, issue_type: str) -> bool:
        """
        Check if an issue type should be suppressed for this file.

        Args:
            issue_type: Type of issue to check

        Returns:
            True if issue should be suppressed
        """
        # Always suppress in vendor/generated files
        if self.is_vendor or self.is_generated:
            return True

        # Check explicit suppression list
        if issue_type in self.suppressed_issues:
            return True

        # Context-based suppression rules
        suppression_rules = {
            FileContext.TEST: [
                "sql_injection",
                "hardcoded_password",
                "hardcoded_secret",
                "weak_password",
                "insecure_random",
            ],
            FileContext.EXAMPLE: [
                "sql_injection",
                "xss",
                "hardcoded_password",
                "missing_error_handling",
                "insecure_config",
            ],
            FileContext.FRAMEWORK: [
                "sql_injection",
                "xss",
                "command_injection",
                "path_traversal",
            ],
            FileContext.DOCUMENTATION: [
                "*"  # Suppress all in documentation
            ],
            FileContext.FIXTURE: [
                "hardcoded_password",
                "hardcoded_secret",
                "weak_password",
                "sensitive_data",
            ],
        }

        # Apply context-based rules
        if self.context in suppression_rules:
            rules = suppression_rules[self.context]
            if "*" in rules or issue_type in rules:
                return True

        return False

    def get_adjusted_severity(self, original_severity: str) -> str:
        """
        Adjust issue severity based on file context.

        Args:
            original_severity: Original severity level

        Returns:
            Adjusted severity level
        """
        # Test files: downgrade severity
        if self.context == FileContext.TEST:
            severity_map = {
                "critical": "high",
                "high": "medium",
                "medium": "low",
                "low": "low",
            }
            return severity_map.get(original_severity.lower(), original_severity)

        # Production files: keep or upgrade severity
        if self.context == FileContext.PRODUCTION:
            if self.is_entry_point:
                # Entry points are more critical
                severity_map = {
                    "critical": "critical",
                    "high": "critical",
                    "medium": "high",
                    "low": "medium",
                }
                return severity_map.get(original_severity.lower(), original_severity)

        return original_severity


@dataclass
class PreAnalysisResult(BaseDomainModel):
    """
    Result of the PRE-ANALYSIS phase.

    Contains project context and file contexts for all analyzed files.
    """

    # Project-level context
    project_context: Any  # ProjectContext (avoiding circular import)

    # File-level contexts
    file_contexts: Dict[str, FileContextInfo] = field(default_factory=dict)  # path -> context

    # Analysis statistics
    total_files_analyzed: int = 0
    files_by_context: Dict[str, int] = field(default_factory=dict)  # context -> count

    # Suppression statistics
    total_suppressions_configured: int = 0
    suppression_by_context: Dict[str, int] = field(default_factory=dict)

    # Performance metrics
    analysis_duration: float = 0.0  # seconds

    def to_json(self) -> Dict[str, Any]:
        """Convert to Panel-compatible JSON."""
        return {
            "projectContext": self.project_context.to_json() if hasattr(self.project_context, 'to_json') else {},
            "fileContexts": {
                path: info.to_json()
                for path, info in self.file_contexts.items()
            },
            "statistics": {
                "totalFilesAnalyzed": self.total_files_analyzed,
                "filesByContext": self.files_by_context,
                "totalSuppressions": self.total_suppressions_configured,
                "suppressionByContext": self.suppression_by_context,
            },
            "analysisDuration": round(self.analysis_duration, 3),
        }

    def get_context_summary(self) -> str:
        """
        Get human-readable summary of context distribution.

        Returns:
            Formatted string with context statistics
        """
        if not self.files_by_context:
            return "No files analyzed"

        summary_parts = []
        for context, count in sorted(self.files_by_context.items()):
            percentage = (count / self.total_files_analyzed) * 100 if self.total_files_analyzed > 0 else 0
            summary_parts.append(f"{context}: {count} ({percentage:.1f}%)")

        return " | ".join(summary_parts)

    def get_production_files(self) -> List[str]:
        """
        Get list of production files.

        Returns:
            List of file paths marked as production context
        """
        return [
            path
            for path, info in self.file_contexts.items()
            if info.context == FileContext.PRODUCTION
        ]

    def get_test_files(self) -> List[str]:
        """
        Get list of test files.

        Returns:
            List of file paths marked as test context
        """
        return [
            path
            for path, info in self.file_contexts.items()
            if info.context == FileContext.TEST
        ]

    def should_analyze_file(self, file_path: str) -> bool:
        """
        Check if a file should be analyzed.

        Args:
            file_path: Path to check

        Returns:
            True if file should be analyzed
        """
        if file_path not in self.file_contexts:
            return True  # Unknown files get analyzed

        context_info = self.file_contexts[file_path]

        # Skip vendor and generated files
        if context_info.is_vendor or context_info.is_generated:
            return False

        # Skip documentation files
        if context_info.context == FileContext.DOCUMENTATION:
            return False

        # Skip files with ignore markers
        if context_info.has_ignore_marker:
            return False

        return True