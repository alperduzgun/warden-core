"""
File Context Analyzer Service.

Analyzes individual files to determine their context (production, test, example, etc.)
for false positive prevention and context-aware analysis.
"""

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import structlog

from warden.analysis.domain.file_context import (
    FileContext,
    FileContextInfo,
    ContextWeights,
)
from warden.analysis.domain.project_context import ProjectContext

logger = structlog.get_logger()


class FileContextAnalyzer:
    """
    Analyzes file context for false positive prevention.

    Part of the PRE-ANALYSIS phase for context detection.
    Supports optional LLM enhancement for ambiguous cases.
    """

    def __init__(
        self,
        project_context: Optional[ProjectContext] = None,
        llm_analyzer: Optional['LlmContextAnalyzer'] = None,
    ) -> None:
        """
        Initialize analyzer.

        Args:
            project_context: Optional project context for better detection
            llm_analyzer: Optional LLM analyzer for enhanced detection
        """
        self.project_context = project_context
        self.llm_analyzer = llm_analyzer
        self.path_patterns = self._compile_path_patterns()
        self.content_patterns = self._compile_content_patterns()

    def analyze_file(self, file_path: Path) -> FileContextInfo:
        """
        Analyze a single file to determine its context (sync version).

        Args:
            file_path: Path to the file to analyze

        Returns:
            FileContextInfo with detected context and metadata
        """
        import asyncio
        try:
            # Try to get existing event loop
            loop = asyncio.get_running_loop()
            # If we're in an async context, we need a workaround
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, self.analyze_file_async(file_path))
                return future.result()
        except RuntimeError:
            # No running loop, create one
            return asyncio.run(self.analyze_file_async(file_path))

    async def analyze_file_async(self, file_path: Path) -> FileContextInfo:
        """
        Analyze a single file to determine its context (async version).

        Args:
            file_path: Path to the file to analyze

        Returns:
            FileContextInfo with detected context and metadata
        """
        file_path = Path(file_path)

        # Multi-layer detection
        context, confidence, method = self._detect_context(file_path)

        # Use LLM if available and confidence is low
        if self.llm_analyzer and confidence < 0.7:
            try:
                # Read file content for LLM
                file_content = None
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        file_content = f.read()[:5000]
                except:
                    pass

                # Enhance with LLM
                from warden.analysis.application.llm_context_analyzer import LlmContextAnalyzer
                if isinstance(self.llm_analyzer, LlmContextAnalyzer):
                    context, confidence, method = await self.llm_analyzer.analyze_file_context(
                        file_path=file_path,
                        initial_context=context,
                        initial_confidence=confidence,
                        file_content=file_content,
                    )
            except Exception as e:
                logger.debug(
                    "llm_enhancement_failed",
                    file=str(file_path),
                    error=str(e),
                )

        # Get appropriate weights for context
        weights = ContextWeights(context=context)

        # Determine suppression rules
        suppressed_issues = self._get_suppressed_issues(context)
        suppression_reason = self._get_suppression_reason(context)

        # Check for special markers
        has_ignore_marker = self._check_ignore_marker(file_path)
        is_entry_point = self._is_entry_point(file_path)
        is_generated = self._is_generated_file(file_path)
        is_vendor = self._is_vendor_file(file_path)

        return FileContextInfo(
            file_path=str(file_path),
            context=context,
            confidence=confidence,
            detection_method=method,
            weights=weights,
            suppressed_issues=suppressed_issues,
            suppression_reason=suppression_reason,
            is_entry_point=is_entry_point,
            is_generated=is_generated,
            is_vendor=is_vendor,
            has_ignore_marker=has_ignore_marker,
        )

    def _detect_context(self, file_path: Path) -> Tuple[FileContext, float, str]:
        """
        Detect file context using multiple strategies.

        Returns:
            (context, confidence, detection_method)
        """
        # Layer 1: Path-based detection (highest priority)
        context = self._detect_by_path(file_path)
        if context and context[1] > 0.9:
            return context[0], context[1], "path"

        # Layer 2: Content-based detection
        context = self._detect_by_content(file_path)
        if context and context[1] > 0.8:
            return context[0], context[1], "content"

        # Layer 3: Import analysis
        context = self._detect_by_imports(file_path)
        if context and context[1] > 0.7:
            return context[0], context[1], "imports"

        # Layer 4: Metadata/comments
        context = self._detect_by_metadata(file_path)
        if context:
            return context[0], context[1], "metadata"

        # Layer 5: Project context hints
        if self.project_context:
            context = self._detect_by_project_context(file_path)
            if context:
                return context[0], context[1], "project_context"

        # Default to production (safest assumption)
        return FileContext.PRODUCTION, 0.5, "default"

    def _compile_path_patterns(self) -> Dict[FileContext, List[re.Pattern]]:
        """Compile regex patterns for path-based detection."""
        patterns = {
            FileContext.TEST: [
                r"test[s]?/",
                r".*test_.*\.py$",
                r".*_test\.py$",
                r"spec[s]?/",
                r".*\.spec\.",
                r"__tests__/",
                r".*\.test\.",
            ],
            FileContext.EXAMPLE: [
                r"example[s]?/",
                r"demo[s]?/",
                r"sample[s]?/",
                r"tutorial[s]?/",
                r".*_example\.",
                r".*_demo\.",
            ],
            FileContext.FRAMEWORK: [
                r"\.warden/frames/",
                r"warden/validation/frames/",
                r".*_frame\.py$",
                r"frames?/",
            ],
            FileContext.DOCUMENTATION: [
                r"\.md$",
                r"\.rst$",
                r"docs?/",
                r"README",
                r"CHANGELOG",
                r"CONTRIBUTING",
            ],
            FileContext.CONFIGURATION: [
                r"\.ya?ml$",
                r"\.json$",
                r"\.toml$",
                r"\.ini$",
                r"\.cfg$",
                r"\.conf$",
                r"config/",
            ],
            FileContext.MIGRATION: [
                r"migrations?/",
                r"migrate/",
                r"alembic/",
                r".*_migration\.py$",
                r"db/migrations?/",
            ],
            FileContext.FIXTURE: [
                r"fixtures?/",
                r"mocks?/",
                r"stubs?/",
                r"fakes?/",
                r".*_fixture\.",
                r".*_mock\.",
            ],
            FileContext.VENDOR: [
                r"vendor/",
                r"node_modules/",
                r"bower_components/",
                r"third_party/",
                r"external/",
                r"\.vendor/",
            ],
            FileContext.GENERATED: [
                r"generated/",
                r"gen/",
                r"build/",
                r"dist/",
                r"_build/",
                r"__pycache__/",
                r".*\.pyc$",
                r".*_pb2\.py$",
                r".*_pb2_grpc\.py$",
            ],
            FileContext.SCRIPT: [
                r"scripts?/",
                r"bin/",
                r"tools?/",
                r"utils?/",
                r".*\.sh$",
                r".*\.bash$",
            ],
        }

        # Compile patterns
        compiled = {}
        for context, pattern_list in patterns.items():
            compiled[context] = [re.compile(p, re.IGNORECASE) for p in pattern_list]

        return compiled

    def _compile_content_patterns(self) -> Dict[FileContext, List[re.Pattern]]:
        """Compile regex patterns for content-based detection."""
        patterns = {
            FileContext.TEST: [
                r"import\s+pytest",
                r"from\s+pytest",
                r"import\s+unittest",
                r"from\s+unittest",
                r"class\s+Test\w+",
                r"def\s+test_\w+",
                r"@pytest\.",
                r"@mock\.",
                r"assert\s+.*==",
                r"self\.assert",
                r"describe\(",
                r"it\(",
                r"expect\(",
            ],
            FileContext.EXAMPLE: [
                r"#\s*Example:",
                r"#\s*Demo:",
                r"#\s*Sample:",
                r"#\s*Usage:",
                r"#\s*Bad:",
                r"#\s*Good:",
                r"#\s*DO NOT USE IN PRODUCTION",
                r"#\s*For demonstration",
            ],
            FileContext.FRAMEWORK: [
                r"class\s+\w+Frame\(",
                r"ValidationFrame",
                r"def\s+detect_pattern",
                r"def\s+check_security",
                r"#\s*Pattern definition",
                r"#\s*Frame implementation",
            ],
            FileContext.MIGRATION: [
                r"def\s+upgrade\(",
                r"def\s+downgrade\(",
                r"class\s+Migration",
                r"schema\.create_table",
                r"schema\.drop_table",
                r"ALTER\s+TABLE",
            ],
        }

        # Compile patterns
        compiled = {}
        for context, pattern_list in patterns.items():
            compiled[context] = [re.compile(p, re.MULTILINE) for p in pattern_list]

        return compiled

    def _detect_by_path(self, file_path: Path) -> Optional[Tuple[FileContext, float]]:
        """Detect context by file path patterns."""
        path_str = str(file_path)

        for context, patterns in self.path_patterns.items():
            for pattern in patterns:
                if pattern.search(path_str):
                    return (context, 0.95)

        return None

    def _detect_by_content(self, file_path: Path) -> Optional[Tuple[FileContext, float]]:
        """Detect context by file content patterns."""
        try:
            # Read first 5000 characters for performance
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read(5000)

            match_counts = {}
            for context, patterns in self.content_patterns.items():
                matches = 0
                for pattern in patterns:
                    if pattern.search(content):
                        matches += 1

                if matches > 0:
                    # Confidence based on match count
                    confidence = min(0.5 + (matches * 0.1), 0.95)
                    match_counts[context] = confidence

            if match_counts:
                # Return highest confidence match
                best_match = max(match_counts.items(), key=lambda x: x[1])
                return best_match

        except Exception as e:
            logger.debug(
                "content_detection_failed",
                file=str(file_path),
                error=str(e),
            )

        return None

    def _detect_by_imports(self, file_path: Path) -> Optional[Tuple[FileContext, float]]:
        """Detect context by import statements."""
        if not file_path.suffix == '.py':
            return None

        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            # Test framework imports
            test_imports = [
                "pytest", "unittest", "nose", "mock",
                "fixtures", "testtools", "hypothesis",
            ]

            for imp in test_imports:
                if f"import {imp}" in content or f"from {imp}" in content:
                    return (FileContext.TEST, 0.85)

            # Framework imports (Warden specific)
            if "from warden.validation.frames" in content:
                return (FileContext.FRAMEWORK, 0.80)

        except Exception:
            pass

        return None

    def _detect_by_metadata(self, file_path: Path) -> Optional[Tuple[FileContext, float]]:
        """Detect context by file metadata or special comments."""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                # Check first 1000 characters for metadata
                content = f.read(1000)

            # Check for explicit context declaration
            if "# warden-context:" in content:
                match = re.search(r"#\s*warden-context:\s*(\w+)", content)
                if match:
                    context_str = match.group(1).lower()
                    for context in FileContext:
                        if context.value == context_str:
                            return (context, 1.0)  # Explicit declaration

            # Check for generated file markers
            if "# Generated by" in content or "# Auto-generated" in content:
                return (FileContext.GENERATED, 0.9)

            # Check for vendor markers
            if "# Third-party" in content or "# External library" in content:
                return (FileContext.VENDOR, 0.9)

        except Exception:
            pass

        return None

    def _detect_by_project_context(self, file_path: Path) -> Optional[Tuple[FileContext, float]]:
        """Use project context hints for detection."""
        if not self.project_context:
            return None

        # Check against special directories
        path_str = str(file_path)

        if "test" in self.project_context.special_dirs:
            for test_dir in self.project_context.special_dirs["test"]:
                if test_dir in path_str:
                    return (FileContext.TEST, 0.8)

        if "vendor" in self.project_context.special_dirs:
            for vendor_dir in self.project_context.special_dirs["vendor"]:
                if vendor_dir in path_str:
                    return (FileContext.VENDOR, 0.9)

        return None

    def _get_suppressed_issues(self, context: FileContext) -> List[str]:
        """Get list of issue types to suppress for context."""
        suppression_map = {
            FileContext.TEST: [
                "sql_injection",
                "hardcoded_password",
                "hardcoded_secret",
                "weak_password",
                "insecure_random",
                "command_injection",
            ],
            FileContext.EXAMPLE: [
                "sql_injection",
                "xss",
                "hardcoded_password",
                "missing_error_handling",
                "insecure_config",
                "path_traversal",
            ],
            FileContext.FRAMEWORK: [
                "sql_injection",
                "xss",
                "command_injection",
                "path_traversal",
                "code_injection",
            ],
            FileContext.FIXTURE: [
                "hardcoded_password",
                "hardcoded_secret",
                "weak_password",
                "sensitive_data",
                "insecure_random",
            ],
            FileContext.DOCUMENTATION: ["*"],  # Suppress all
            FileContext.VENDOR: ["*"],  # Suppress all
            FileContext.GENERATED: ["*"],  # Suppress all
        }

        return suppression_map.get(context, [])

    def _get_suppression_reason(self, context: FileContext) -> Optional[str]:
        """Get suppression reason for context."""
        reasons = {
            FileContext.TEST: "Test files often contain intentional vulnerabilities",
            FileContext.EXAMPLE: "Example code demonstrates patterns including anti-patterns",
            FileContext.FRAMEWORK: "Framework code contains pattern definitions",
            FileContext.FIXTURE: "Test fixtures contain mock data",
            FileContext.DOCUMENTATION: "Documentation contains code examples",
            FileContext.VENDOR: "Third-party code should not be modified",
            FileContext.GENERATED: "Generated code should not be manually modified",
        }

        return reasons.get(context)

    def _check_ignore_marker(self, file_path: Path) -> bool:
        """Check if file has ignore marker."""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read(1000)

            ignore_markers = [
                "warden-ignore",
                "warden:ignore",
                "noqa: warden",
                "pylint: skip-file",
            ]

            return any(marker in content for marker in ignore_markers)

        except Exception:
            return False

    def _is_entry_point(self, file_path: Path) -> bool:
        """Check if file is an entry point."""
        entry_names = [
            "main.py", "app.py", "index.py", "__main__.py",
            "run.py", "start.py", "server.py", "wsgi.py",
            "index.js", "app.js", "main.js", "server.js",
        ]

        return file_path.name in entry_names

    def _is_generated_file(self, file_path: Path) -> bool:
        """Check if file is generated."""
        # Check path
        path_str = str(file_path)
        generated_patterns = [
            "__pycache__", ".pyc", "_pb2.py", "_pb2_grpc.py",
            "generated/", "gen/", "build/", "dist/",
        ]

        return any(pattern in path_str for pattern in generated_patterns)

    def _is_vendor_file(self, file_path: Path) -> bool:
        """Check if file is vendor/third-party."""
        path_str = str(file_path)
        vendor_patterns = [
            "vendor/", "node_modules/", "bower_components/",
            "third_party/", "external/", ".vendor/",
        ]

        return any(pattern in path_str for pattern in vendor_patterns)