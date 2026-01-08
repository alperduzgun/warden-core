"""
Architectural Consistency Frame

Validates architectural and organizational standards:
1. File Size Limits - Max 500 lines per file
2. Function Size Limits - Max 50 lines per function
3. Class Count - Max 5 classes per file
4. Frame Organization - Frame-per-directory pattern
5. Test Mirror - Tests mirror source structure
6. __init__.py Presence - All packages have __init__.py
7. Naming Conventions - Follow PEP 8 and project standards

Priority: MEDIUM
Blocker: FALSE (warnings only)
Scope: FILE_LEVEL + PROJECT_LEVEL

Author: Warden Team
Version: 2.0 (Enhanced with organization checks)
Date: 2025-12-21
"""

import ast
import time
from pathlib import Path
from typing import Dict, Any, List, Optional
import yaml
import re
import fnmatch
from dataclasses import dataclass

from warden.validation.domain.frame import (
    ValidationFrame,
    FrameResult,
    Finding,
    CodeFile,
)
from warden.validation.domain.enums import (
    FrameCategory,
    FramePriority,
    FrameScope,
)
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)


@dataclass
class OrganizationViolation:
    """Organization rule violation."""

    rule: str
    severity: str  # 'error' | 'warning'
    message: str
    file_path: str
    expected: Optional[str] = None
    actual: Optional[str] = None


class ArchitecturalConsistencyFrame(ValidationFrame):
    """
    Architectural Consistency Frame

    Validates code organization and architectural standards.

    Checks:
    - File size limits (500 lines max)
    - Function complexity (50 lines max)
    - Class count (5 max per file)
    - Frame organization (frame-per-directory)
    - Test structure (mirrors source)
    - __init__.py presence
    - Naming conventions
    """

    # Required metadata
    name = "Architectural Consistency Local"
    description = "Validates SOLID principles, file organization, and project structure (Local Enhanced)"
    category = FrameCategory.LANGUAGE_SPECIFIC
    priority = FramePriority.MEDIUM
    scope = FrameScope.FILE_LEVEL
    is_blocker = False
    version = "2.0.0"
    author = "Warden Team"

    def __init__(self, config: Dict[str, Any] | None = None):
        """
        Initialize ArchitecturalFrame.

        Args:
            config: Frame configuration
                - max_file_lines: int (default: 500)
                - max_function_lines: int (default: 50)
                - max_classes_per_file: int (default: 5)
                - check_organization: bool (default: True)
                - check_test_mirror: bool (default: True)
                - check_naming: bool (default: True)
        """
        super().__init__(config)

        # Ensure config is a dict
        config_dict = self.config if isinstance(self.config, dict) else {}

        # Size limits
        self.max_file_lines = config_dict.get("max_file_lines", 500)
        self.max_function_lines = config_dict.get("max_function_lines", 50)
        self.max_classes_per_file = config_dict.get("max_classes_per_file", 5)

        # Organization checks
        self.check_organization = config_dict.get("check_organization", True)
        self.check_test_mirror = config_dict.get("check_test_mirror", True)
        self.check_naming = config_dict.get("check_naming", True)
        self.check_placement = config_dict.get("check_placement", True)

        # Standard project structure for placement checks
        self.standard_structure = config_dict.get("standard_structure", {
            "src/warden/semantic_search": "Top-level feature module",
            "src/warden/analysis/application": "Core analysis orchestration",
            "src/warden/validation/frames": "Validation frame definitions",
            "src/warden/shared/services": "Cross-cutting shared services",
        })

        # Root Hygiene
        self.check_root_hygiene = config_dict.get("check_root_hygiene", True)
        self.allowed_root_files = {
            "README.md", "LICENSE", "pyproject.toml", "setup.py", ".gitignore",
            ".dockerignore", "Dockerfile", "Makefile", "requirements.txt",
            ".env", ".env.example", ".warden", ".git", ".github", ".vscode",
            ".idea", "warden.yaml", "warden.yml", "GEMINI.md", "CLAUDE.md",
            "poetry.lock", "start_warden_chat.sh"
        }
        
        # Module Placement Rules (Forbidden Path -> Correct Path)
        self.placement_rules = {
            "semantic_search": {
                "forbidden": "src/warden/analysis/application/semantic_search",
                "expected": "src/warden/semantic_search"
            },
            "mcp_cli_leak": {
                "forbidden": "src/warden/cli/mcp",
                "expected": "src/warden/mcp"
            },
            "mcp_service_leak": {
                "forbidden": "src/warden/services/mcp",
                "expected": "src/warden/mcp"
            }
        }
        
        # Load custom rules from conventions.yaml
        self.custom_rules = self._load_custom_rules()

    def _load_custom_rules(self) -> List[Dict[str, Any]]:
        """Load custom rules from .warden/rules/conventions.yaml"""
        try:
            # Try to find project root by looking for .warden
            # Heuristic: go up until .warden is found, or use CWD
            cwd = Path.cwd()
            rules_path = cwd / ".warden" / "rules" / "conventions.yaml"
            
            if not rules_path.exists():
                return []
                
            with open(rules_path, 'r') as f:
                data = yaml.safe_load(f)
                return data.get('custom_rules', [])
        except Exception as e:
            logger.error(f"Failed to load custom rules: {e}")
            return []

    async def execute(self, code_file: CodeFile) -> FrameResult:
        """
        Execute architectural validation.

        Args:
            code_file: Code file to validate

        Returns:
            FrameResult with architectural findings
        """
        start_time = time.perf_counter()

        logger.info(
            "architectural_frame_started",
            file_path=code_file.path,
            language=code_file.language,
        )

        violations: List[OrganizationViolation] = []
        scenarios_executed: List[str] = []

        try:
            # 1. File size check
            scenarios_executed.append("File size limit check")
            file_violations = self._check_file_size(code_file)
            violations.extend(file_violations)

            # 2. Function/class complexity checks (Python only)
            if code_file.language.lower() == "python":
                scenarios_executed.append("Function size check")
                func_violations = self._check_function_size(code_file)
                violations.extend(func_violations)

                scenarios_executed.append("Class count check")
                class_violations = self._check_class_count(code_file)
                violations.extend(class_violations)

            # 3. Frame organization check
            if self.check_organization and self._is_frame_file(code_file.path):
                scenarios_executed.append("Frame organization check")
                org_violations = self._check_frame_organization(code_file.path)
                violations.extend(org_violations)

            # 4. Test mirror check
            if self.check_test_mirror and not self._is_test_file(code_file.path):
                scenarios_executed.append("Test mirror structure check")
                mirror_violations = self._check_test_mirror_structure(code_file.path)
                violations.extend(mirror_violations)

            # 5. __init__.py check
            if code_file.language.lower() == "python":
                scenarios_executed.append("__init__.py presence check")
                init_violations = self._check_init_py_presence(code_file.path)
                violations.extend(init_violations)

            # 6. Naming convention check
            if self.check_naming:
                scenarios_executed.append("Naming convention check")
                naming_violations = self._check_naming_conventions(code_file.path)
                violations.extend(naming_violations)

                scenarios_executed.append("Async naming check")
                async_violations = self._check_async_naming(code_file)
                violations.extend(async_violations)
            
            # 7. Custom Rules (YAML)
            if self.custom_rules:
                scenarios_executed.append("Custom YAML rules check")
                custom_violations = self._check_custom_rules(code_file)
                violations.extend(custom_violations)

            # 8. Module placement check
            if self.check_placement:
                scenarios_executed.append("Module placement check")
                placement_violations = self._check_module_placement(code_file.path)
                violations.extend(placement_violations)

            # 9. Service abstraction consistency check (context-aware)
            if hasattr(self, 'project_context') and self.project_context:
                scenarios_executed.append("Service abstraction consistency check")
                abstraction_violations = self._check_service_abstraction_consistency(code_file)
                violations.extend(abstraction_violations)

            # 10. Root Hygiene check (AI-Driven)
            if self.check_root_hygiene:
                scenarios_executed.append("Root Hygiene check")
                # Need project root to determine if file is in root
                # Assuming project_context has root_path or we derive from path
                root_violations = await self._check_root_hygiene(code_file)
                violations.extend(root_violations)

            # Convert violations to findings
            findings = self._violations_to_findings(violations, code_file)

            # Determine status (warnings don't fail)
            status = "warning" if violations else "passed"

            duration = time.perf_counter() - start_time

            logger.info(
                "architectural_frame_completed",
                file_path=code_file.path,
                status=status,
                violations=len(violations),
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
                    "errors": sum(1 for v in violations if v.severity == "error"),
                    "warnings": sum(1 for v in violations if v.severity == "warning"),
                    "scenarios_executed": scenarios_executed,
                },
            )

        except Exception as e:
            logger.error(
                "architectural_frame_error",
                file_path=code_file.path,
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

    # ============================================
    # SIZE & COMPLEXITY CHECKS
    # ============================================

    def _check_file_size(self, code_file: CodeFile) -> List[OrganizationViolation]:
        """Check if file exceeds size limit."""
        violations = []

        line_count = len(code_file.content.split('\n'))

        if line_count > self.max_file_lines:
            violations.append(OrganizationViolation(
                rule="max_file_lines",
                severity="error",
                message=f"File exceeds {self.max_file_lines} lines ({line_count} lines) - violates Single Responsibility Principle",
                file_path=code_file.path,
                expected=f"≤ {self.max_file_lines} lines",
                actual=f"{line_count} lines",
            ))

        return violations

    def _check_function_size(self, code_file: CodeFile) -> List[OrganizationViolation]:
        """Check if functions exceed size limit."""
        violations = []

        try:
            tree = ast.parse(code_file.content)

            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    if hasattr(node, 'end_lineno') and hasattr(node, 'lineno'):
                        func_lines = node.end_lineno - node.lineno

                        if func_lines > self.max_function_lines:
                            violations.append(OrganizationViolation(
                                rule="max_function_lines",
                                severity="warning",
                                message=f"Function '{node.name}' is {func_lines} lines - should be ≤ {self.max_function_lines} lines",
                                file_path=f"{code_file.path}:{node.lineno}",
                                expected=f"≤ {self.max_function_lines} lines",
                                actual=f"{func_lines} lines",
                            ))

        except SyntaxError:
            # Skip if file has syntax errors
            pass

        return violations

    def _check_class_count(self, code_file: CodeFile) -> List[OrganizationViolation]:
        """Check if file has too many classes."""
        violations = []

        try:
            tree = ast.parse(code_file.content)

            class_count = sum(1 for node in ast.walk(tree) if isinstance(node, ast.ClassDef))

            if class_count > self.max_classes_per_file:
                violations.append(OrganizationViolation(
                    rule="max_classes_per_file",
                    severity="warning",
                    message=f"{class_count} classes in one file - consider splitting (max {self.max_classes_per_file})",
                    file_path=code_file.path,
                    expected=f"≤ {self.max_classes_per_file} classes",
                    actual=f"{class_count} classes",
                ))

        except SyntaxError:
            pass

        return violations

    # ============================================
    # ORGANIZATION CHECKS
    # ============================================

    def _is_frame_file(self, file_path: str) -> bool:
        """Check if file is a validation frame."""
        return "validation/frames" in file_path and file_path.endswith("_frame.py")

    def _is_test_file(self, file_path: str) -> bool:
        """Check if file is a test file."""
        return "tests/" in file_path or file_path.endswith("_test.py") or file_path.startswith("test_")

    def _check_frame_organization(self, file_path: str) -> List[OrganizationViolation]:
        """
        Check if frame follows frame-per-directory pattern.

        Expected:
        - frames/orphan/orphan_frame.py ✅
        - frames/orphan_frame.py ❌ (flat, deprecated)
        """
        violations = []

        path = Path(file_path)

        # Extract frame name from filename
        # Example: orphan_frame.py → orphan
        if path.name.endswith("_frame.py"):
            frame_name = path.name.replace("_frame.py", "")

            # Check if file is in correct directory
            # Expected: .../frames/{frame_name}/{frame_name}_frame.py
            parent_dir = path.parent.name

            if parent_dir != frame_name:
                violations.append(OrganizationViolation(
                    rule="frame_per_directory",
                    severity="error",
                    message=f"Frame file should be in '{frame_name}/' directory (frame-per-directory pattern)",
                    file_path=file_path,
                    expected=f"frames/{frame_name}/{frame_name}_frame.py",
                    actual=f"frames/{parent_dir}/{path.name}",
                ))

        return violations

    def _check_test_mirror_structure(self, file_path: str) -> List[OrganizationViolation]:
        """
        Check if source file has corresponding test file.

        Expected:
        - src/warden/validation/frames/orphan/orphan_frame.py
        - tests/validation/frames/orphan/test_orphan_frame.py ✅
        """
        violations = []

        # Only check files in src/warden/
        if "src/warden/" not in file_path:
            return violations

        path = Path(file_path)

        # Build expected test path
        # src/warden/validation/frames/orphan/orphan_frame.py
        # → tests/validation/frames/orphan/test_orphan_frame.py

        parts = path.parts
        try:
            warden_idx = parts.index("warden")
            relative_parts = parts[warden_idx + 1:]  # After "warden"

            # Build test path
            test_filename = f"test_{path.name}"
            test_path_parts = ["tests"] + list(relative_parts[:-1]) + [test_filename]

            # Find project root (go up from src/warden/)
            src_idx = parts.index("src")
            project_root = Path(*parts[:src_idx])

            expected_test_path = project_root / Path(*test_path_parts)

            if not expected_test_path.exists():
                violations.append(OrganizationViolation(
                    rule="test_mirror_structure",
                    severity="warning",
                    message=f"No corresponding test file found",
                    file_path=file_path,
                    expected=str(expected_test_path),
                    actual="Test file missing",
                ))

        except (ValueError, IndexError):
            # Can't determine expected test path
            pass

        return violations

    def _check_init_py_presence(self, file_path: str) -> List[OrganizationViolation]:
        """
        Check if package has __init__.py file.

        Every directory with Python files should have __init__.py.
        """
        violations = []

        path = Path(file_path)
        parent_dir = path.parent

        # Check if parent directory has __init__.py
        init_file = parent_dir / "__init__.py"

        if not init_file.exists():
            violations.append(OrganizationViolation(
                rule="init_py_presence",
                severity="error",
                message=f"Package directory missing __init__.py",
                file_path=str(parent_dir),
                expected="__init__.py present",
                actual="__init__.py missing",
            ))

        return violations

    def _check_naming_conventions(self, file_path: str) -> List[OrganizationViolation]:
        """
        Check naming conventions.

        Rules:
        - File names: lowercase_with_underscores.py
        - Frame files: {frame_name}_frame.py
        - Directory names: lowercase_with_underscores
        """
        violations = []

        path = Path(file_path)

        # Check file name (no uppercase, no hyphens)
        if path.suffix == ".py":
            filename = path.stem

            # Check for uppercase
            if filename != filename.lower():
                violations.append(OrganizationViolation(
                    rule="filename_lowercase",
                    severity="warning",
                    message=f"File name should be lowercase with underscores",
                    file_path=file_path,
                    expected="lowercase_with_underscores.py",
                    actual=path.name,
                ))

            # Check for hyphens
            if "-" in filename:
                violations.append(OrganizationViolation(
                    rule="filename_no_hyphens",
                    severity="warning",
                    message="File name should use underscores, not hyphens",
                    file_path=file_path,
                    expected=filename.replace("-", "_") + ".py",
                    actual=path.name,
                ))

        return violations

    def _check_async_naming(self, code_file: CodeFile) -> List[OrganizationViolation]:
        """
        Check if async methods end with '_async'.

        Rule: convention.naming.asyncMethodSuffix = "_async"
        Exceptions: test_*, __*, setup, teardown
        """
        violations = []
        if code_file.language.lower() != "python":
            return violations

        try:
            tree = ast.parse(code_file.content)
            
            for node in ast.walk(tree):
                if isinstance(node, ast.AsyncFunctionDef):
                    name = node.name
                    
                    # Exceptions
                    if (
                        name.startswith("test_") or 
                        name.startswith("__") or
                        name in ["setup", "teardown", "setUp", "tearDown"]
                    ):
                        continue
                        
                    if not name.endswith("_async"):
                        violations.append(OrganizationViolation(
                            rule="async_naming_convention",
                            severity="warning",
                            message=f"Async method '{name}' should end with '_async' suffix",
                            file_path=f"{code_file.path}:{node.lineno}",
                            expected=f"{name}_async",
                            actual=name,
                        ))
        except SyntaxError:
            pass
            
        return violations

    def _check_module_placement(self, file_path: str) -> List[OrganizationViolation]:
        """
        Check if the file is placed in the correct architectural layer.
        
        Example: 
        - semantic_search should be top-level feature, not under analysis/application
        """
        violations = []
        path_str = file_path.replace("\\", "/") # Normalize paths
        
        violations = []
        path_str = file_path.replace("\\", "/") # Normalize paths
        
        for rule_name, rule in self.placement_rules.items():
            forbidden = rule["forbidden"]
            expected = rule["expected"]
            
            if forbidden in path_str:
                violations.append(OrganizationViolation(
                    rule=f"module_placement_{rule_name}",
                    severity="error",
                    message=f"Feature found in forbidden path '{forbidden}'. Should be in '{expected}'.",
                    file_path=file_path,
                    expected=f"{expected}/...",
                    actual=path_str,
                ))
        
        return violations

    # ============================================
    # HELPERS
    # ============================================

    def _violations_to_findings(
        self,
        violations: List[OrganizationViolation],
        code_file: CodeFile,
    ) -> List[Finding]:
        """Convert violations to Frame findings."""
        findings = []

        for i, violation in enumerate(violations):
            finding = Finding(
                id=f"{self.frame_id}-{violation.rule}-{i}",
                severity="medium" if violation.severity == "error" else "low",
                message=violation.message,
                location=violation.file_path,
                detail=(
                    f"**Rule:** {violation.rule}\n\n"
                    f"**Expected:** {violation.expected}\n\n"
                    f"**Actual:** {violation.actual}\n\n"
                    if violation.expected else violation.message
                ),
                code=None,  # No code snippet for organization violations
            )
            findings.append(finding)

        return findings

    def _check_service_abstraction_consistency(
        self, 
        code_file: CodeFile
    ) -> List[OrganizationViolation]:
        """
        Check if code bypasses detected service abstractions.
        
        Uses context-aware detection: if the project has a SecretManager,
        flag direct os.getenv usage for secrets.
        
        Example:
            Project has: SecretManager (handles secrets)
            File uses: os.getenv("API_KEY")
            → Violation: Use SecretManager instead
        """
        violations = []
        
        # Get service abstractions from project context
        service_abstractions = getattr(self.project_context, 'service_abstractions', {})
        
        if not service_abstractions:
            return violations
        
        # Check each line for bypass patterns
        lines = code_file.content.split('\n')
        
        for line_num, line in enumerate(lines, 1):
            for service_name, abstraction in service_abstractions.items():
                # Get bypass patterns for this service
                bypass_patterns = abstraction.get('bypass_patterns', [])
                keywords = abstraction.get('responsibility_keywords', [])
                category = abstraction.get('category', 'custom')
                
                # Check if line contains any bypass pattern
                for pattern in bypass_patterns:
                    if pattern in line:
                        # Check if the bypass is for a relevant keyword
                        # e.g., os.getenv("API_KEY") where API_KEY is relevant
                        line_upper = line.upper()
                        relevant = any(kw in line_upper for kw in keywords)
                        
                        if relevant:
                            violations.append(OrganizationViolation(
                                rule="service_abstraction_bypass",
                                severity="warning",
                                message=f"Use {service_name} instead of direct '{pattern}'",
                                file_path=f"{code_file.path}:{line_num}",
                                expected=f"Use {service_name} (project has {category} abstraction)",
                                actual=line.strip()[:80],
                            ))
                            break  # One violation per line per service
        
        return violations

    def set_project_context(self, context: Any) -> None:
        """
        Set the project context for context-aware checks.
        
        Called by FrameExecutor to inject project context.
        
        Args:
            context: ProjectContext with service_abstractions
        """
        self.project_context = context

    async def _check_root_hygiene(self, code_file: CodeFile) -> List[OrganizationViolation]:
        """
        Check if file belongs in project root using AI context.
        """
        violations = []
        path = Path(code_file.path)
        
        # 1. Determine Project Root
        # If project_context is available, use it. Otherwise assume cwd or git root logic.
        project_root = None
        if hasattr(self, 'project_context') and self.project_context:
            if hasattr(self.project_context, 'project_root'):
                project_root = Path(self.project_context.project_root)
        
        if not project_root:
            # Fallback: assume running from root
            project_root = Path.cwd()

        # Check if file is directly in root
        if path.parent.resolve() != project_root.resolve():
            logger.info("root_hygiene_skip_not_root", path=str(path), parent=str(path.parent.resolve()), root=str(project_root.resolve()))
            return violations  # Not a root file, skip

        logger.info("root_hygiene_checking", path=str(path))

        # 2. Fast Pass (Allowlist)
        if path.name in self.allowed_root_files:
            return violations
        
        # Common false positives & Garbage Detection
        if path.suffix in ['.lock', '.log', '.xml']:
             # Logs
             if path.suffix == '.log':
                 violations.append(OrganizationViolation(
                    rule="root_hygiene_log",
                    severity="warning",
                    message=f"Log file '{path.name}' found in root. Move to logs/ directory.",
                    file_path=code_file.path,
                    expected="logs/*.log",
                    actual=f"/{path.name}"
                ))
                 return violations
             
             # Coverage artifacts
             if path.name in ['coverage.xml', '.coverage']:
                 violations.append(OrganizationViolation(
                    rule="root_hygiene_artifact",
                    severity="warning",
                    message=f"Build/Test artifact '{path.name}' found in root. Add to .gitignore or clean up.",
                    file_path=code_file.path,
                    expected="Artifacts in .gitignore",
                    actual=f"/{path.name}"
                 ))
                 return violations

        # Temporary Scripts match
        if path.name.startswith("verify_") or path.name.startswith("tmp_") or path.name.startswith("temp_"):
             violations.append(OrganizationViolation(
                rule="root_hygiene_script",
                severity="warning",
                message=f"Temporary script '{path.name}' found in root. Move to scripts/ or delete.",
                file_path=code_file.path,
                expected="scripts/*.py",
                actual=f"/{path.name}"
            ))
             return violations
        
        # Binary/Script detection (no extension)
        if not path.suffix and path.name not in self.allowed_root_files:
             # Likely a binary or shell script
             violations.append(OrganizationViolation(
                rule="root_hygiene_binary",
                severity="warning",
                message=f"Unknown executable/file '{path.name}' found in root. Move to bin/ or scripts/.",
                file_path=code_file.path,
                expected="bin/",
                actual=f"/{path.name}"
            ))
             return violations

        # 3. Semantic Similarity Pass (Find clones in src/)
        # If this file is a copy-paste or refactor of something in src/, it's misplaced.
        if hasattr(self, 'semantic_search_service') and self.semantic_search_service:
            try:
                # Search for similar code in project
                # We assume semantic_search_service has a search method returning results with score
                search_results = await self.semantic_search_service.search_async(
                    query=code_file.content, 
                    k=1,
                    threshold=0.85 
                )
                
                if search_results:
                    best_match = search_results[0]
                    # If match is in src/, then this root file is likely a duplicate or misplaced code
                    if "src/" in best_match.metadata.get("path", ""):
                        violations.append(OrganizationViolation(
                            rule="root_hygiene_misplaced_code",
                            severity="warning",
                            message=f"File content is {best_match.score:.2f} similar to {best_match.metadata.get('path')}. Move implementation to src/.",
                            file_path=code_file.path,
                            expected=f"Consolidate with {best_match.metadata.get('path')}",
                            actual="Duplicate in root",
                        ))
                        return violations
            except Exception as e:
                logger.error(f"Semantic search failed during hygiene check: {e}")

        # 4. LLM Judgment (Slow Pass) - Only if enabled and ambiguous
        # (This section is computationally expensive, so it's the last resort)
        # We'll skip implementation here as requested by user to focus on rules
        
        return violations

    def _check_custom_rules(self, code_file: CodeFile) -> List[OrganizationViolation]:
        """
        Check custom regex rules defined in YAML.
        """
        violations = []
        path = Path(code_file.path)
        
        for rule in self.custom_rules:
            # Check applicability
            matches_file = False
            file_patterns = rule.get('files', ["*"])
            for pattern in file_patterns:
                if fnmatch.fnmatch(path.name, pattern):
                    matches_file = True
                    break
            
            if not matches_file:
                continue
                
            # Check exclusion
            excluded = False
            for pattern in rule.get('exclude', []):
                # Simple exclusion check on name or full path components
                if fnmatch.fnmatch(path.name, pattern) or fnmatch.fnmatch(str(path), pattern):
                    excluded = True
                    break
            
            if excluded:
                continue
                
            # Regex check
            regex_pattern = rule.get('pattern')
            if not regex_pattern:
                continue
                
            try:
                if re.search(regex_pattern, code_file.content, re.MULTILINE):
                    violations.append(OrganizationViolation(
                        rule=f"custom_{rule.get('id', 'unknown')}",
                        severity=rule.get('severity', 'warning'),
                        message=rule.get('message', f"Matches pattern '{regex_pattern}'"),
                        file_path=code_file.path,
                        expected=f"Not match '{regex_pattern}'",
                        actual="Pattern found",
                    ))
            except re.error as e:
                logger.error(f"Invalid regex pattern in rule {rule.get('id')}: {e}")
                
        return violations
