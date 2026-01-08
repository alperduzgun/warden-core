"""
Enhanced pipeline orchestrator with discovery, build context, and suppression.

Extends the base PipelineOrchestrator with optional pre/post-processing phases:
- Pre: File discovery (finds all project files)
- Pre: Build context loading (extracts dependency info)
- Post: Suppression filtering (removes false positives)
"""

import asyncio
from typing import List, Dict, Any, Optional
from pathlib import Path

from warden.pipeline.application.orchestrator import PhaseOrchestrator
from warden.pipeline.domain.models import (
    PipelineConfig,
    PipelineResult,
)
from warden.validation.domain.frame import ValidationFrame, CodeFile
from warden.analysis.application.discovery import FileDiscoverer, DiscoveredFile
from warden.build_context import BuildContextProvider, BuildContext
from warden.suppression import SuppressionMatcher, load_suppression_config
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)


class EnhancedPipelineOrchestrator(PhaseOrchestrator):
    """
    Enhanced pipeline orchestrator with optional discovery, build context, and suppression.

    This orchestrator extends the base pipeline with three optional phases:

    1. **Discovery Phase** (Pre-validation):
       - Scans project directory for code files
       - Respects .gitignore patterns
       - Filters by file type
       - Only runs if enable_discovery=True

    2. **Build Context Phase** (Pre-validation):
       - Loads build configuration (package.json, pyproject.toml, etc.)
       - Extracts dependency information
       - Makes build context available to frames
       - Only runs if enable_build_context=True

    3. **Suppression Phase** (Post-validation):
       - Filters findings using suppression rules
       - Supports inline comments and config files
       - Removes false positives
       - Only runs if enable_suppression=True

    All phases are optional and controlled by PipelineConfig flags.
    """

    def __init__(
        self,
        frames: List[ValidationFrame],
        config: Optional[PipelineConfig] = None,
    ) -> None:
        """
        Initialize enhanced orchestrator.

        Args:
            frames: List of validation frames to execute
            config: Pipeline configuration (with optional phase flags)
        """
        super().__init__(frames, config)

        # Phase tracking
        self.discovery_result: Optional[Any] = None
        self.build_context: Optional[BuildContext] = None
        self.suppression_matcher: Optional[SuppressionMatcher] = None

        logger.info(
            "enhanced_orchestrator_initialized",
            frame_count=len(frames),
            discovery_enabled=self.config.enable_discovery,
            build_context_enabled=self.config.enable_build_context,
            suppression_enabled=self.config.enable_suppression,
        )

    async def execute_with_discovery(self, project_path: str) -> PipelineResult:
        """
        Execute pipeline with automatic file discovery.

        This is the main entry point for the enhanced pipeline. It:
        1. Discovers files in the project (if enabled)
        2. Loads build context (if enabled)
        3. Converts discovered files to CodeFile objects
        4. Runs validation frames on all files
        5. Applies suppression filtering (if enabled)

        Args:
            project_path: Root path of the project to analyze

        Returns:
            PipelineResult with aggregated findings

        Example:
            >>> orchestrator = EnhancedPipelineOrchestrator(frames=[SecurityFrame()])
            >>> result = await orchestrator.execute_with_discovery("/path/to/project")
            >>> print(f"Total findings: {result.total_findings}")
        """
        logger.info(
            "enhanced_pipeline_started",
            project_path=project_path,
        )

        # Phase 1: Discovery (if enabled)
        code_files = await self._discover_files_phase(project_path)

        # Phase 2: Build context (if enabled)
        await self._load_build_context_phase(project_path)

        # Phase 3: Run validation frames
        result = await super().execute(code_files)

        # Phase 4: Apply suppression (if enabled)
        result = await self._apply_suppression_phase(result)

        logger.info(
            "enhanced_pipeline_completed",
            project_path=project_path,
            total_files=len(code_files),
            total_findings=result.total_findings,
            suppressed_findings=result.metadata.get("suppressed_count", 0),
        )

        return result

    async def _discover_files_phase(self, project_path: str) -> List[CodeFile]:
        """
        Phase 1: Discover files in project.

        Args:
            project_path: Root path of project

        Returns:
            List of CodeFile objects to analyze
        """
        if not self.config.enable_discovery:
            logger.info("discovery_phase_skipped", reason="disabled_in_config")
            # Return empty list - caller must provide files manually
            return []

        logger.info("discovery_phase_started", project_path=project_path)

        try:
            # Get discovery configuration
            discovery_config = self.config.discovery_config or {}
            max_depth = discovery_config.get("max_depth")
            use_gitignore = discovery_config.get("use_gitignore", True)

            # Create discoverer
            discoverer = FileDiscoverer(
                root_path=project_path,
                max_depth=max_depth,
                use_gitignore=use_gitignore,
            )

            # Run discovery
            self.discovery_result = await discoverer.discover_async()

            # Convert to CodeFile objects
            code_files = await self._convert_to_code_files(
                self.discovery_result.get_analyzable_files()
            )

            logger.info(
                "discovery_phase_completed",
                total_files=self.discovery_result.stats.total_files,
                analyzable_files=len(code_files),
                duration=f"{self.discovery_result.stats.scan_duration_seconds:.2f}s",
            )

            return code_files

        except Exception as e:
            logger.error(
                "discovery_phase_failed",
                project_path=project_path,
                error=str(e),
            )
            # Return empty list on error
            return []

    async def _convert_to_code_files(
        self, discovered_files: List[DiscoveredFile]
    ) -> List[CodeFile]:
        """
        Convert DiscoveredFile objects to CodeFile objects.

        Args:
            discovered_files: List of discovered files

        Returns:
            List of CodeFile objects with loaded content
        """
        code_files: List[CodeFile] = []

        for discovered_file in discovered_files:
            try:
                # Read file content
                file_path = Path(discovered_file.path)
                content = file_path.read_text(encoding="utf-8")

                # Determine language from file extension
                language = self._get_language_from_extension(file_path.suffix)

                # Create CodeFile
                code_file = CodeFile(
                    path=str(file_path),
                    content=content,
                    language=language,
                    framework=None,  # Framework detection happens at project level
                    size_bytes=discovered_file.size_bytes,
                )

                code_files.append(code_file)

            except Exception as e:
                logger.warning(
                    "file_load_failed",
                    file_path=discovered_file.path,
                    error=str(e),
                )
                continue

        return code_files

    def _get_language_from_extension(self, extension: str) -> str:
        """
        Get language name from file extension.

        Args:
            extension: File extension (e.g., '.py', '.js')

        Returns:
            Language name
        """
        from warden.shared.utils.language_utils import get_language_from_path
        # get_language_from_path expects a Path or string with extension
        # If we only have extension, we can create a dummy path
        return get_language_from_path(f"dummy{extension}").value

    async def _load_build_context_phase(self, project_path: str) -> None:
        """
        Phase 2: Load build context from project.

        Args:
            project_path: Root path of project
        """
        if not self.config.enable_build_context:
            logger.info("build_context_phase_skipped", reason="disabled_in_config")
            return

        logger.info("build_context_phase_started", project_path=project_path)

        try:
            # Create build context provider
            provider = BuildContextProvider(project_path)

            # Load context asynchronously
            self.build_context = await provider.get_context_async()

            logger.info(
                "build_context_phase_completed",
                build_system=self.build_context.build_system.value,
                project_name=self.build_context.project_name,
                dependency_count=len(self.build_context.dependencies),
            )

        except Exception as e:
            logger.warning(
                "build_context_phase_failed",
                project_path=project_path,
                error=str(e),
            )
            # Continue without build context
            self.build_context = None

    async def _apply_suppression_phase(self, result: PipelineResult) -> PipelineResult:
        """
        Phase 4: Apply suppression filtering to results.

        Args:
            result: Pipeline result with findings

        Returns:
            Pipeline result with suppressed findings removed
        """
        if not self.config.enable_suppression:
            logger.info("suppression_phase_skipped", reason="disabled_in_config")
            return result

        logger.info(
            "suppression_phase_started",
            total_findings_before=result.total_findings,
        )

        try:
            # Load suppression config
            if not self.suppression_matcher:
                self.suppression_matcher = await self._load_suppression_matcher()

            if not self.suppression_matcher:
                logger.warning("suppression_matcher_not_available")
                return result

            # Filter findings in each frame result
            suppressed_count = 0

            for frame_result in result.frame_results:
                original_count = len(frame_result.findings)
                filtered_findings = []

                for finding in frame_result.findings:
                    # Extract line number from location (format: "path:line")
                    line_number = self._extract_line_number(finding.location)

                    # Check if suppressed
                    if not self.suppression_matcher.is_suppressed(
                        line=line_number,
                        rule=finding.id,
                        code=None,  # We don't have code context here
                        file_path=self._extract_file_path(finding.location),
                    ):
                        filtered_findings.append(finding)
                    else:
                        suppressed_count += 1

                # Update findings
                frame_result.findings = filtered_findings
                frame_result.issues_found = len(filtered_findings)

            # Update totals
            result.total_findings -= suppressed_count
            result.metadata["suppressed_count"] = suppressed_count
            result.metadata["suppression_enabled"] = True

            logger.info(
                "suppression_phase_completed",
                total_findings_after=result.total_findings,
                suppressed_count=suppressed_count,
            )

            return result

        except Exception as e:
            logger.error(
                "suppression_phase_failed",
                error=str(e),
            )
            # Return original result on error
            return result

    async def _load_suppression_matcher(self) -> Optional[SuppressionMatcher]:
        """
        Load suppression matcher from configuration.

        Returns:
            SuppressionMatcher instance or None if not available
        """
        try:
            # Load from config file if specified
            if self.config.suppression_config_path:
                config = load_suppression_config(self.config.suppression_config_path)
            else:
                # Try default location
                default_path = ".warden/suppressions.yaml"
                if Path(default_path).exists():
                    config = load_suppression_config(default_path)
                else:
                    # No config file, use empty matcher
                    from warden.suppression.models import SuppressionConfig

                    config = SuppressionConfig()

            return SuppressionMatcher(config)

        except Exception as e:
            logger.warning(
                "suppression_matcher_load_failed",
                error=str(e),
            )
            return None

    def _extract_line_number(self, location: str) -> int:
        """
        Extract line number from location string.

        Args:
            location: Location string (format: "path:line" or "path:line:col")

        Returns:
            Line number (1-indexed), or 1 if cannot parse
        """
        try:
            parts = location.split(":")
            if len(parts) >= 2:
                return int(parts[1])
        except (ValueError, IndexError):
            pass

        return 1  # Default to line 1

    def _extract_file_path(self, location: str) -> str:
        """
        Extract file path from location string.

        Args:
            location: Location string (format: "path:line" or "path:line:col")

        Returns:
            File path
        """
        parts = location.split(":")
        if parts:
            return parts[0]
        return ""

    def get_discovery_result(self) -> Optional[Any]:
        """
        Get the discovery result from the last execution.

        Returns:
            DiscoveryResult or None if discovery was not run
        """
        return self.discovery_result

    def get_build_context(self) -> Optional[BuildContext]:
        """
        Get the build context from the last execution.

        Returns:
            BuildContext or None if build context was not loaded
        """
        return self.build_context

    def get_suppression_matcher(self) -> Optional[SuppressionMatcher]:
        """
        Get the suppression matcher used in the last execution.

        Returns:
            SuppressionMatcher or None if suppression was not enabled
        """
        return self.suppression_matcher
