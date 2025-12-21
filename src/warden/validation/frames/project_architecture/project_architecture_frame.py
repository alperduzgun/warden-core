"""
Project Architecture Frame - PROJECT-LEVEL validation.

This frame operates on the ENTIRE PROJECT structure (not individual files).
It detects architectural and organizational issues that can only be seen
at the project level:

1. Empty Modules - Directories with only empty __init__.py
2. Duplicate Modules - Same functionality in multiple locations
3. Architectural Inconsistency - Mixed Clean Architecture + Analyzer Pattern
4. Model Duplication - Same models in different paths
5. Unnecessary Layers - Over-engineering for project type

Priority: HIGH
Blocker: FALSE (architectural warnings)
Scope: PROJECT_LEVEL (runs once per project, not per file!)

Author: Warden Team
Version: 1.0.0
Date: 2025-12-21
"""

import time
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

from warden.validation.domain.frame import ValidationFrame, FrameResult, Finding
from warden.validation.domain.enums import (
    FrameCategory,
    FramePriority,
    FrameScope,
)
from warden.shared.domain.project_context import ProjectContext, ModuleInfo
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ArchitecturalViolation:
    """Architectural violation at project level."""

    rule: str
    severity: str  # 'error' | 'warning' | 'info'
    message: str
    location: str
    expected: Optional[str] = None
    actual: Optional[str] = None
    suggestion: Optional[str] = None


class ProjectArchitectureFrame(ValidationFrame):
    """
    Project Architecture Validation Frame.

    This frame analyzes the ENTIRE PROJECT structure and detects:
    - Empty modules (only __init__.py, no actual code)
    - Duplicate modules (same implementation in multiple locations)
    - Architectural pattern inconsistencies
    - Model duplication across packages
    - Unnecessary architectural layers

    Unlike file-level frames, this runs ONCE per project scan.
    """

    # Required metadata
    name = "Project Architecture Analysis"
    description = "Validates project-level architectural patterns and module organization"
    category = FrameCategory.GLOBAL
    priority = FramePriority.HIGH  # Important, but not critical
    scope = FrameScope.PROJECT_LEVEL  # ✅ PROJECT-LEVEL!
    is_blocker = False  # Architectural warnings don't block
    version = "1.0.0"
    author = "Warden Team"

    def __init__(self, config: Dict[str, Any] | None = None) -> None:
        """
        Initialize ProjectArchitectureFrame.

        Args:
            config: Frame configuration
                - detect_empty_modules: bool (default: True)
                - detect_duplicates: bool (default: True)
                - detect_pattern_mixing: bool (default: True)
                - detect_unnecessary_layers: bool (default: True)
                - strict_mode: bool (default: False) - Treat warnings as errors
        """
        super().__init__(config)

        # Detection flags
        self.detect_empty_modules = self.config.get("detect_empty_modules", True)
        self.detect_duplicates = self.config.get("detect_duplicates", True)
        self.detect_pattern_mixing = self.config.get("detect_pattern_mixing", True)
        self.detect_unnecessary_layers = self.config.get(
            "detect_unnecessary_layers", True
        )
        self.strict_mode = self.config.get("strict_mode", False)

    async def execute(self, project_context: ProjectContext) -> FrameResult:
        """
        Execute project-level architectural validation.

        NOTE: This method receives ProjectContext (not CodeFile)!

        Args:
            project_context: Complete project structure context

        Returns:
            FrameResult with architectural violations
        """
        start_time = time.perf_counter()

        logger.info(
            "project_architecture_frame_started",
            project_root=str(project_context.root_path),
            total_modules=len(project_context.modules),
        )

        violations: List[ArchitecturalViolation] = []

        try:
            # 1. Detect empty modules
            if self.detect_empty_modules:
                logger.debug("detecting_empty_modules")
                empty_violations = self._detect_empty_modules(project_context)
                violations.extend(empty_violations)

            # 2. Detect duplicate modules
            if self.detect_duplicates:
                logger.debug("detecting_duplicate_modules")
                duplicate_violations = self._detect_duplicate_modules(project_context)
                violations.extend(duplicate_violations)

            # 3. Detect architectural pattern mixing
            if self.detect_pattern_mixing:
                logger.debug("detecting_pattern_mixing")
                pattern_violations = self._detect_pattern_mixing(project_context)
                violations.extend(pattern_violations)

            # 4. Detect unnecessary layers
            if self.detect_unnecessary_layers:
                logger.debug("detecting_unnecessary_layers")
                layer_violations = self._detect_unnecessary_layers(project_context)
                violations.extend(layer_violations)

            # Convert violations to findings
            findings = self._violations_to_findings(violations, project_context)

            # Determine status
            status = self._determine_status(violations)

            duration = time.perf_counter() - start_time

            logger.info(
                "project_architecture_frame_completed",
                project_root=str(project_context.root_path),
                status=status,
                total_violations=len(violations),
                empty_modules=sum(1 for v in violations if v.rule == "empty_module"),
                duplicates=sum(1 for v in violations if v.rule == "duplicate_module"),
                pattern_issues=sum(
                    1 for v in violations if v.rule == "mixed_architecture"
                ),
                layer_issues=sum(
                    1 for v in violations if v.rule == "unnecessary_layer"
                ),
                duration=f"{duration:.2f}s",
            )

            return FrameResult(
                frame_id=self.frame_id,
                frame_name=self.name,
                status=status,
                duration=duration,
                issues_found=len(violations),
                is_blocker=False,
                findings=findings,
                metadata={
                    "total_violations": len(violations),
                    "empty_modules": sum(
                        1 for v in violations if v.rule == "empty_module"
                    ),
                    "duplicate_modules": sum(
                        1 for v in violations if v.rule == "duplicate_module"
                    ),
                    "architectural_issues": sum(
                        1 for v in violations if v.rule == "mixed_architecture"
                    ),
                    "unnecessary_layers": sum(
                        1 for v in violations if v.rule == "unnecessary_layer"
                    ),
                    "project_modules": len(project_context.modules),
                    "total_files": len(project_context.all_files),
                },
            )

        except Exception as e:
            logger.error(
                "project_architecture_frame_error",
                project_root=str(project_context.root_path),
                error=str(e),
            )

            duration = time.perf_counter() - start_time
            return FrameResult(
                frame_id=self.frame_id,
                frame_name=self.name,
                status="failed",
                duration=duration,
                issues_found=0,
                is_blocker=False,
                findings=[],
                metadata={
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
            )

    # ==============================================
    # DETECTION METHODS
    # ==============================================

    def _detect_empty_modules(
        self, project_context: ProjectContext
    ) -> List[ArchitecturalViolation]:
        """
        Detect empty modules (only __init__.py with minimal content).

        Example violation:
        - src/warden/api/api/__init__.py (only empty file)
        """
        violations = []

        empty_modules = project_context.get_empty_modules()

        for module in empty_modules:
            violations.append(
                ArchitecturalViolation(
                    rule="empty_module",
                    severity="warning",
                    message=f"Empty module '{module.name}' contains only empty __init__.py",
                    location=str(module.path),
                    expected="Module with actual code",
                    actual="Only empty __init__.py",
                    suggestion=(
                        "Remove this empty module or add actual implementation. "
                        "Empty modules add unnecessary complexity."
                    ),
                )
            )

        return violations

    def _detect_duplicate_modules(
        self, project_context: ProjectContext
    ) -> List[ArchitecturalViolation]:
        """
        Detect duplicate module implementations.

        Example violation:
        - src/warden/core/validation/frames/security.py
        - src/warden/validation/frames/security/security_frame.py
        (Both implement SecurityFrame!)
        """
        violations = []

        # Find files with duplicate names
        duplicate_files = project_context.get_duplicate_files()

        for filename, paths in duplicate_files.items():
            # Skip common files (__init__.py, conftest.py, etc.)
            if filename in ["__init__.py", "conftest.py", "__main__.py"]:
                continue

            # Skip test files (test duplication is okay)
            if filename.startswith("test_"):
                continue

            # Check if files are in different module hierarchies
            module_names = set()
            for path in paths:
                # Get module name (parent directory structure)
                parts = path.parts
                if "src" in parts:
                    src_idx = parts.index("src")
                    module_parts = parts[src_idx + 1 : -1]  # Exclude filename
                    module_names.add(".".join(module_parts))

            # If different modules have same file, it's likely a duplicate
            if len(module_names) > 1:
                violations.append(
                    ArchitecturalViolation(
                        rule="duplicate_module",
                        severity="error",
                        message=f"Duplicate file '{filename}' found in {len(paths)} locations",
                        location=", ".join(str(p) for p in paths[:3]),
                        expected="Single implementation",
                        actual=f"{len(paths)} duplicate files",
                        suggestion=(
                            "Keep one implementation and remove duplicates. "
                            "Multiple implementations of the same module cause confusion and maintenance issues."
                        ),
                    )
                )

        return violations

    def _detect_pattern_mixing(
        self, project_context: ProjectContext
    ) -> List[ArchitecturalViolation]:
        """
        Detect mixed architectural patterns.

        Example violation:
        - Project has both Clean Architecture AND Analyzer Pattern
        """
        violations = []

        has_clean_arch = project_context.has_clean_architecture_pattern()
        has_analyzer = project_context.has_analyzer_pattern()

        if has_clean_arch and has_analyzer:
            violations.append(
                ArchitecturalViolation(
                    rule="mixed_architecture",
                    severity="error",
                    message="Project uses BOTH Clean Architecture AND Analyzer Pattern - inconsistent!",
                    location=str(project_context.root_path),
                    expected="Single consistent architectural pattern",
                    actual="Mixed: Clean Architecture + Analyzer Pattern",
                    suggestion=(
                        "Choose ONE architectural pattern:\n"
                        "1. Clean Architecture (api/application/domain/infrastructure) - Good for complex backends\n"
                        "2. Analyzer Pattern (analyzers/validation/models) - Good for analysis tools\n"
                        "3. Document hybrid approach with clear module boundaries"
                    ),
                )
            )

        return violations

    def _detect_unnecessary_layers(
        self, project_context: ProjectContext
    ) -> List[ArchitecturalViolation]:
        """
        Detect unnecessary architectural layers for project type.

        Example violation:
        - CLI tool has REST API layer (unnecessary!)
        """
        violations = []

        # Check if CLI/TUI tool
        is_cli = project_context.is_cli_tool()

        if is_cli:
            # Check for API modules (unnecessary for CLI tools)
            api_modules = project_context.get_modules_by_pattern("*.api.*")

            if api_modules:
                violations.append(
                    ArchitecturalViolation(
                        rule="unnecessary_layer",
                        severity="warning",
                        message=f"Found {len(api_modules)} API modules in CLI tool - likely unnecessary",
                        location=", ".join(m.name for m in api_modules[:3]),
                        expected="No API layer for CLI tool",
                        actual=f"{len(api_modules)} API modules found",
                        suggestion=(
                            "CLI/TUI tools don't need REST API layers. "
                            "Consider removing 'api/' directories and simplifying architecture."
                        ),
                    )
                )

            # Check for application service layers (potentially overkill)
            app_modules = project_context.get_modules_by_pattern("*.application.*")

            if len(app_modules) > 5:  # 5+ application service modules = overkill
                violations.append(
                    ArchitecturalViolation(
                        rule="unnecessary_layer",
                        severity="info",
                        message=f"Found {len(app_modules)} application service modules - potentially over-engineered",
                        location=", ".join(m.name for m in app_modules[:3]),
                        expected="Minimal layers for tool-type project",
                        actual=f"{len(app_modules)} application modules",
                        suggestion=(
                            "For analysis tools, application service layers may be overkill. "
                            "Consider simplifying to: analyzers/ + models/ + cli/"
                        ),
                    )
                )

        return violations

    # ==============================================
    # HELPERS
    # ==============================================

    def _violations_to_findings(
        self,
        violations: List[ArchitecturalViolation],
        project_context: ProjectContext,
    ) -> List[Finding]:
        """Convert violations to Frame findings."""
        findings = []

        for i, violation in enumerate(violations):
            # Map severity
            severity_map = {
                "error": "high",
                "warning": "medium",
                "info": "low",
            }
            severity = severity_map.get(violation.severity, "medium")

            # Build detail message
            detail = f"**Rule:** {violation.rule}\n\n"
            if violation.expected:
                detail += f"**Expected:** {violation.expected}\n\n"
            if violation.actual:
                detail += f"**Actual:** {violation.actual}\n\n"
            if violation.suggestion:
                detail += f"**Suggestion:**\n{violation.suggestion}"

            finding = Finding(
                id=f"{self.frame_id}-{violation.rule}-{i}",
                severity=severity,
                message=violation.message,
                location=violation.location,
                detail=detail,
                code=None,  # No code snippet for project-level violations
            )
            findings.append(finding)

        return findings

    def _determine_status(self, violations: List[ArchitecturalViolation]) -> str:
        """Determine frame status based on violations."""
        if not violations:
            return "passed"

        # Check for errors
        has_errors = any(v.severity == "error" for v in violations)

        if has_errors:
            if self.strict_mode:
                return "failed"  # Strict mode: errors = failure
            else:
                return "warning"  # Normal mode: errors = warning
        else:
            return "warning"  # Only warnings/info
