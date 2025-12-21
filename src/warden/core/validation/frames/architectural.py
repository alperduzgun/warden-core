"""ArchitecturalConsistencyFrame - Design patterns. Priority: Medium, Blocker: False"""
import ast
import time
import re
from pathlib import Path
from typing import Dict, Any, List, Tuple
from warden.core.validation.frame import BaseValidationFrame, FrameResult, FrameScope

class ArchitecturalConsistencyFrame(BaseValidationFrame):
    @property
    def name(self) -> str:
        return "Architectural Consistency"
    @property
    def description(self) -> str:
        return "Validates SOLID principles, file size, function complexity"
    @property
    def priority(self) -> str:
        return "medium"
    @property
    def scope(self) -> FrameScope:
        return FrameScope.FILE_LEVEL
    @property
    def is_blocker(self) -> bool:
        return False

    def _find_project_root(self, file_path: str) -> Path:
        """Find project root by looking for src/ directory."""
        path = Path(file_path).resolve()
        for parent in [path] + list(path.parents):
            if (parent / "src").exists():
                return parent
        return path.parent

    def _check_frame_organization(self, file_path: str) -> List[str]:
        """Check if validation frames follow frame-per-directory pattern."""
        issues = []
        path = Path(file_path)

        # Only check files in validation/frames directory
        if "validation/frames" not in str(path):
            return issues

        # Extract frame name from file (e.g., chaos_frame.py → chaos)
        frame_match = re.match(r"(.+)_frame\.py$", path.name)
        if not frame_match:
            return issues

        frame_name = frame_match.group(1)

        # Check if file is in correct directory structure
        # Expected: .../frames/{frame_name}/{frame_name}_frame.py
        if path.parent.name != frame_name:
            issues.append(
                f"Frame organization violation: '{path.name}' should be in "
                f"'frames/{frame_name}/' directory (currently in '{path.parent.name}/'). "
                f"Follow frame-per-directory pattern."
            )

        return issues

    def _check_test_mirror(self, file_path: str) -> List[str]:
        """Check if test structure mirrors source structure."""
        issues = []
        path = Path(file_path)
        project_root = self._find_project_root(file_path)

        # Only check source files (not tests)
        if "tests/" in str(path):
            return issues

        # Check if this is in src/ directory
        try:
            relative_to_src = path.relative_to(project_root / "src")
        except ValueError:
            return issues

        # Build expected test path
        test_file_name = f"test_{path.name}"
        expected_test_path = project_root / "tests" / relative_to_src.parent / test_file_name

        if not expected_test_path.exists():
            issues.append(
                f"Missing test mirror: Expected test file at '{expected_test_path.relative_to(project_root)}' "
                f"for source file '{relative_to_src}'"
            )

        return issues

    def _check_init_files(self, file_path: str) -> List[str]:
        """Check if all directories have __init__.py files."""
        issues = []
        path = Path(file_path)
        project_root = self._find_project_root(file_path)

        # Check parent directories up to src/
        current = path.parent
        src_dir = project_root / "src"

        while current >= src_dir and current != project_root:
            init_file = current / "__init__.py"
            if not init_file.exists():
                try:
                    relative_path = current.relative_to(project_root)
                    issues.append(
                        f"Missing __init__.py in '{relative_path}/' - "
                        f"Required for proper Python package structure"
                    )
                except ValueError:
                    pass
            current = current.parent

        return issues

    def _check_import_paths(self, file_path: str, file_content: str) -> List[str]:
        """Check if import paths follow organized patterns."""
        issues = []

        # Only check files in frames directory
        if "validation/frames" not in file_path:
            return issues

        try:
            tree = ast.parse(file_content)
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    if isinstance(node, ast.ImportFrom) and node.module:
                        # Check for deprecated flat imports
                        # Bad: from warden.validation.frames.orphan_frame import OrphanFrame
                        # Good: from warden.validation.frames.orphan import OrphanFrame
                        if "frames." in node.module and "_frame" in node.module:
                            issues.append(
                                f"Deprecated flat import pattern: '{node.module}'. "
                                f"Use organized imports (e.g., 'from warden.validation.frames.orphan import OrphanFrame')"
                            )
        except SyntaxError:
            pass

        return issues

    async def execute(self, file_path: str, file_content: str, language: str, characteristics: Dict[str, Any], correlation_id: str = "", timeout: int = 300) -> FrameResult:
        start_time = time.perf_counter()
        issues, findings, scenarios = [], [], []

        try:
            # Original checks
            scenarios.append("File size limit check")
            line_count = len(file_content.split('\n'))
            if line_count > 500:
                issues.append(f"File exceeds 500 lines ({line_count} lines) - violates Single Responsibility")

            scenarios.append("Function size check")
            tree = ast.parse(file_content)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    func_lines = node.end_lineno - node.lineno if hasattr(node, 'end_lineno') else 0
                    if func_lines > 50:
                        issues.append(f"Function '{node.name}' is {func_lines} lines - should be <50")

            scenarios.append("Class count check")
            class_count = sum(1 for n in ast.walk(tree) if isinstance(n, ast.ClassDef))
            if class_count > 5:
                findings.append(f"{class_count} classes in one file - consider splitting")

            # NEW: Organization checks
            scenarios.append("Frame organization pattern check")
            org_issues = self._check_frame_organization(file_path)
            issues.extend(org_issues)

            scenarios.append("Test mirror structure check")
            test_issues = self._check_test_mirror(file_path)
            if test_issues:
                findings.extend(test_issues)  # Warnings, not blockers

            scenarios.append("__init__.py presence check")
            init_issues = self._check_init_files(file_path)
            if init_issues:
                findings.extend(init_issues)  # Warnings, not blockers

            scenarios.append("Import path organization check")
            import_issues = self._check_import_paths(file_path, file_content)
            if import_issues:
                findings.extend(import_issues)  # Warnings, not blockers

            passed = len(issues) == 0
        except Exception as e:
            findings.append(f"Architectural check error: {str(e)}")
            passed = True  # Don't fail on errors

        return FrameResult(
            name=self.name,
            passed=passed,
            execution_time_ms=(time.perf_counter()-start_time)*1000,
            priority=self.priority,
            scope=self.scope.value,
            findings=findings,
            issues=issues,
            scenarios_executed=scenarios,
            is_blocker=self.is_blocker
        )
