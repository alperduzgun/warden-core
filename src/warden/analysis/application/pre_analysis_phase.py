"""
PRE-ANALYSIS Phase Orchestrator.

Phase 0 of the 6-phase pipeline that analyzes project structure and file contexts
to enable context-aware analysis and false positive prevention.
"""

import asyncio
import fnmatch
import hashlib
import re
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import structlog

from warden.analysis.application.dependency_graph import DependencyGraph
from warden.analysis.application.file_context_analyzer import FileContextAnalyzer
from warden.analysis.application.integrity_scanner import IntegrityScanner
from warden.analysis.application.project_purpose_detector import ProjectPurposeDetector
from warden.analysis.application.project_structure_analyzer import ProjectStructureAnalyzer
from warden.analysis.domain.file_context import (
    FileContext,
    PreAnalysisResult,
)
from warden.analysis.domain.project_context import ProjectContext
from warden.ast.application.provider_loader import ASTProviderLoader
from warden.ast.application.provider_registry import ASTProviderRegistry
from warden.ast.domain.enums import CodeLanguage
from warden.memory.application.memory_manager import MemoryManager
from warden.shared.utils.hasher import NormalizedHasher
from warden.shared.utils.language_utils import get_language_from_path
from warden.validation.domain.frame import CodeFile

logger = structlog.get_logger()

# Context-Aware Criticality Map
# Defines which file patterns are "Critical" (must be LLM verified) for specific project types.
# All other low-confidence files in these project types will be handled by Rust/Rule-based only.
CRITICALITY_MAP = {
    "mobile": [
        "android/key.properties", "**/android/key.properties",
        "ios/*.plist", "**/ios/*.plist",
        "lib/main.dart", "lib/**/*auth*", "lib/**/*config*", "lib/**/*service*",
        "pubspec.yaml", "**/pubspec.yaml"
    ],
    "web": [
        "src/App.*", "src/main.*", "src/**/*auth*", "src/**/*config*",
        "vite.config.*", "next.config.*", ".env*"
    ],
    "backend": [
        "settings.py", "**/settings.py",
        "config.py", "**/config.py",
        "models.py", "**/models.py",
        "auth.py", "**/auth.py",
        "security.py", "**/security.py",
        "pyproject.toml", "poetry.lock"
    ]
}

class PreAnalysisPhase:
    """
    PRE-ANALYSIS Phase orchestrator (Phase 0).

    Analyzes project structure and determines file contexts before
    the main analysis pipeline begins. This enables context-aware
    analysis and false positive prevention.
    """

    def __init__(
        self,
        project_root: Path,
        progress_callback: Callable | None = None,
        config: dict[str, Any] | None = None,
        rate_limiter: Any | None = None,
        llm_service: Any | None = None,
    ) -> None:
        """
        Initialize PRE-ANALYSIS phase.

        Args:
            project_root: Root directory of the project
            progress_callback: Optional callback for progress updates
            config: Optional configuration including LLM settings
            rate_limiter: Optional rate limiter for LLM calls
            llm_service: Optional shared LLM service.
        """
        self.project_root = Path(project_root)
        self.progress_callback = progress_callback
        self.config = config or {}
        self.rate_limiter = rate_limiter
        self.llm_service = llm_service

        # Initialize analyzers
        from warden.pipeline.domain.enums import AnalysisLevel
        self.project_analyzer = ProjectStructureAnalyzer(
            self.project_root,
            llm_config=self.config.get("llm_config"),
            analysis_level=self.config.get("analysis_level", AnalysisLevel.STANDARD),
            llm_service=self.llm_service
        )
        self.file_analyzer: FileContextAnalyzer | None = None  # Created after project analysis
        self.llm_analyzer = None  # Will be initialized if enabled

        self.memory_manager = MemoryManager(self.project_root)
        self.env_hash = self._calculate_environment_hash()

        # AST and Dependency Infrastructure
        self.ast_registry = ASTProviderRegistry()
        self.ast_loader = ASTProviderLoader(self.ast_registry)
        self.dependency_graph: DependencyGraph | None = None  # Initialized in execute
        self.integrity_scanner = IntegrityScanner(self.project_root, self.ast_registry, self.config.get("integrity_config"))

        # Linter Infrastructure (Phase 0 Check)
        from warden.analysis.services.linter_service import LinterService
        self.linter_service = LinterService()

        # Intelligence Infrastructure (CI Optimization)
        self.intelligence_loader = None
        if self.config.get("ci_mode"):
            try:
                from warden.analysis.services.intelligence_loader import IntelligenceLoader
                self.intelligence_loader = IntelligenceLoader(self.project_root)
                if self.intelligence_loader.load():
                    logger.info(
                        "intelligence_loaded_for_ci",
                        modules=len(self.intelligence_loader.get_module_map()),
                        quality=self.intelligence_loader.get_quality_score()
                    )
            except Exception as e:
                logger.debug("intelligence_load_skipped", error=str(e))

    async def execute_async(
        self,
        code_files: list[CodeFile],
        pipeline_context: Any | None = None
    ) -> PreAnalysisResult:
        """
        Execute PRE-ANALYSIS phase.

        Args:
            code_files: List of code files to analyze
            pipeline_context: Optional pipeline context for shared state (AST cache)

        Returns:
            PreAnalysisResult with project and file contexts
        """
        start_time = time.perf_counter()
        logger.info(
            "pre_analysis_phase_started",
            project_root=str(self.project_root),
            file_count=len(code_files),
        )

        # Notify progress
        if self.progress_callback:
            self.progress_callback("pre_analysis_started", {
                "phase": "pre_analysis",
                "total_files": len(code_files),
            })

        try:
            # Step 1: Initialize LLM analyzer if enabled
            await self._initialize_llm_analyzer_async()

            # Initialize memory
            await self.memory_manager.initialize_async()

            # Step 2: Analyze project structure
            # Initialize empty context and enrich from memory first
            project_context = ProjectContext(
                project_root=str(self.project_root),
                project_name=self.project_root.name,
            )
            self._enrich_context_from_memory(project_context)

            # Validate Environment Hash
            is_env_valid = self._validate_environment_hash()
            if not is_env_valid:
                logger.warning("environment_changed", reason="config_or_version_mismatch", action="invalidating_context_cache")

            self.trust_memory_context = is_env_valid

            # Analyze structure (will only discover purpose if missing after enrichment)
            all_paths = [Path(cf.path) for cf in code_files]
            project_context = await self._analyze_project_structure_async(project_context, all_files=all_paths)

            # Ensure AST providers are loaded for integrity check
            await self.ast_loader.load_all()

            # Step 2.5: Integrity Check (Fail-Fast)
            # Scan files for syntax validity and optional build verification
            # Skip in BASIC level to hit performance targets
            from warden.pipeline.domain.enums import AnalysisLevel
            analysis_level = self.config.get("analysis_level", AnalysisLevel.STANDARD)

            if analysis_level != AnalysisLevel.BASIC:
                integrity_issues = await self.integrity_scanner.scan_async(code_files, project_context, pipeline_context)
                if integrity_issues:
                    # Log issues
                    for issue in integrity_issues:
                        logger.error("integrity_check_failure", file=issue.file_path, error=issue.message)

                    # Check for critical failures (syntax errors or build failures)
                    fail_fast = self.config.get("integrity_config", {}).get("fail_fast", True)
                    if fail_fast:
                        logger.error("integrity_check_failed_aborting", issue_count=len(integrity_issues))
                        raise RuntimeError(f"Integrity check failed with {len(integrity_issues)} issues. Fix syntax/build errors before running Warden.")
            else:
                logger.info("skipping_integrity_check_for_basic_level")

            # Step 3: Dependency Awareness (Impact Analysis)
            # Skip in BASIC level to hit performance targets
            if analysis_level != AnalysisLevel.BASIC:
                impacted_files = await self._identify_impacted_files_async(code_files, project_context)
            else:
                logger.info("skipping_dependency_impact_analysis_for_basic_level")
                impacted_files = set()

            # Step 4: Initialize file analyzer with project context and LLM
            self.file_analyzer = FileContextAnalyzer(project_context, self.llm_analyzer)

            # Step 5: Analyze file contexts in parallel
            file_contexts = await self._analyze_file_contexts_async(code_files, impacted_files)

            # Step 5: Calculate statistics
            statistics = self._calculate_statistics(file_contexts)

            # Step 6: Tool Discovery (Pre-Flight Check)
            # Detect available linters (Fail Fast / Degradation)
            if self.linter_service:
                await self.linter_service.detect_and_setup(project_context)

            # Create result
            result = PreAnalysisResult(
                project_context=project_context,
                file_contexts=file_contexts,
                total_files_analyzed=len(file_contexts),
                files_by_context=statistics["files_by_context"],
                total_suppressions_configured=statistics["total_suppressions"],
                suppression_by_context=statistics["suppression_by_context"],
                analysis_duration=time.perf_counter() - start_time,
            )

            logger.info(
                "pre_analysis_phase_completed",
                project_type=project_context.project_type.value,
                framework=project_context.framework.value,
                files_analyzed=result.total_files_analyzed,
                context_distribution=result.files_by_context,
                duration=result.analysis_duration,
            )

            # Notify completion
            if self.progress_callback:
                self.progress_callback("pre_analysis_completed", {
                    "phase": "pre_analysis",
                    "project_type": project_context.project_type.value,
                    "framework": project_context.framework.value,
                    "contexts": result.get_context_summary(),
                    "duration": f"{result.analysis_duration:.2f}s",
                })


            # Step 6: Save learning to memory
            await self._save_context_to_memory_async(project_context)

            # Step 7: Save file states (hashes)
            # We save this now so next run knows about these hashes
            await self.save_file_states_async(file_contexts)

            # Step 8: Save current environment hash
            if self.memory_manager and self.memory_manager._is_loaded:
                self.memory_manager.update_environment_hash(self.env_hash)
                await self.memory_manager.save_async()

            # Step 9: Trigger Semantic Indexing (Smart Incremental)
            try:
                from warden.pipeline.domain.enums import AnalysisLevel
                from warden.shared.services.semantic_search_service import SemanticSearchService

                ss_config = self.config.get("semantic_search", {})
                ss_service = SemanticSearchService(ss_config)

                # Skip semantic indexing in BASIC level
                analysis_level = self.config.get("analysis_level", AnalysisLevel.STANDARD)

                if ss_service.is_available() and analysis_level != AnalysisLevel.BASIC:
                    logger.info("triggering_semantic_indexing")
                    if self.progress_callback:
                        self.progress_callback("semantic_indexing_started", {
                            "phase": "pre_analysis",
                            "action": "indexing_codebase"
                        })

                    await ss_service.index_project(self.project_root, [Path(cf.path) for cf in code_files])

                    if self.progress_callback:
                        self.progress_callback("semantic_indexing_completed", {
                            "phase": "pre_analysis",
                            "action": "indexing_codebase_done"
                        })
            except Exception as e:
                logger.error("semantic_indexing_failed", error=str(e))

            return result

        except RuntimeError as e:
            # Propagate critical errors immediately (like integrity check violations)
            raise e
        except Exception as e:
            logger.error(
                "pre_analysis_phase_failed",
                error=str(e),
            )

            # Return minimal result on failure
            return PreAnalysisResult(
                project_context=ProjectContext(
                    project_root=str(self.project_root),
                    project_name=self.project_root.name,
                ),
                file_contexts={},
                analysis_duration=time.perf_counter() - start_time,
            )

    async def _initialize_llm_analyzer_async(self) -> None:
        """Initialize LLM analyzer if enabled in config."""
        # Check for use_llm in config
        from warden.pipeline.domain.enums import AnalysisLevel
        use_llm = self.config.get("use_llm", True)
        analysis_level = self.config.get("analysis_level", AnalysisLevel.STANDARD)

        if not use_llm or analysis_level == AnalysisLevel.BASIC:
            logger.info("llm_disabled_for_pre_analysis", reason="config_or_level")
            return

        try:
            from warden.analysis.application.llm_context_analyzer import LlmContextAnalyzer
            from warden.llm.config import load_llm_config_async

            # Load LLM configuration
            llm_config = await load_llm_config_async()

            # Get PRE-ANALYSIS specific config
            pre_analysis_config = self.config.get("pre_analysis") or {}
            confidence_threshold = pre_analysis_config.get("llm_threshold", 0.7)
            batch_size = pre_analysis_config.get("batch_size", 10)

            # Rate limit config (default to conservative but usable limits)
            # tpm = pre_analysis_config.get("tpm", 30000)  # 30k tokens/min
            # rpm = pre_analysis_config.get("rpm", 100)    # 100 req/min

            # Initialize shared Rate Limiter for this phase
            # rate_limiter = RateLimiter(RateLimitConfig(tpm=tpm, rpm=rpm))

            # Use injected rate limiter or fallback (though fallback shouldn't happen with correct dependency injection)
            rate_limiter = self.rate_limiter

            # Initialize LLM analyzer
            self.llm_analyzer = LlmContextAnalyzer(
                llm_config=llm_config,
                confidence_threshold=confidence_threshold,
                batch_size=batch_size,
                cache_enabled=True,
                rate_limiter=rate_limiter,
                llm_service=self.llm_service,
            )

            logger.info(
                "llm_analyzer_initialized",
                confidence_threshold=confidence_threshold,
                batch_size=batch_size,
            )

        except Exception as e:
            logger.warning(
                "llm_initialization_failed",
                error=str(e),
                fallback="rule-based detection only",
            )
            self.llm_analyzer = None

    async def _analyze_project_structure_async(
        self,
        initial_context: ProjectContext | None = None,
        all_files: list[Path] | None = None
    ) -> ProjectContext:
        """
        Analyze project structure and characteristics.

        Args:
            initial_context: Optional pre-initialized context
            all_files: Optional list of pre-discovered files

        Returns:
            ProjectContext with detected information
        """
        logger.info("analyzing_project_structure")

        # Run project structure analysis
        project_context = await self.project_analyzer.analyze_async(initial_context, all_files=all_files)

        # Step 2.1: Semantic Discovery (Purpose and Architecture)
        # Check if we already have it in memory via enrichment (called in execute)
        from warden.pipeline.domain.enums import AnalysisLevel
        analysis_level = self.config.get("analysis_level", AnalysisLevel.STANDARD)

        if not project_context.purpose and self.llm_analyzer and analysis_level != AnalysisLevel.BASIC:
            detector = ProjectPurposeDetector(
                self.project_root,
                llm_config=self.config.get("llm_config"),
                llm_service=self.llm_service
            )
            # We need the file list for discovery canvas
            # Use analyzer's filtered list to avoid pollution (like __pycache__)
            all_files = self.project_analyzer.get_all_files()
            purpose, arch, modules = await detector.detect_async(
                all_files,
                project_context.config_files
            )
            project_context.purpose = purpose
            project_context.architecture_description = arch
            # Store module map in project context if available
            if modules and hasattr(project_context, 'modules'):
                project_context.modules = modules
            logger.info("semantic_discovery_completed", purpose=purpose[:50] + "...")

        logger.info(
            "project_structure_analyzed",
            project_type=project_context.project_type.value,
            framework=project_context.framework.value,
            architecture=project_context.architecture.value,
            purpose=project_context.purpose[:50] + "..." if project_context.purpose else "None",
            confidence=project_context.confidence,
        )

        return project_context

    async def _analyze_file_contexts_async(
        self,
        code_files: list[CodeFile],
        impacted_files: set[str] = None
    ) -> dict[str, Any]:
        """
        Analyze context for each file using Rule-based pass → Semantic Spread → Batch LLM.

        Args:
            code_files: List of code files to analyze
            impacted_files: Files that must be re-analyzed regardless of cache

        Returns:
            Dictionary mapping file paths to FileContextInfo
        """
        logger.info(
            "analyzing_file_contexts_optimized",
            file_count=len(code_files),
            mode="batch_plus_semantic"
        )

        # STEP 1: Rule-based fast pass (LLM disabled here)
        tasks = []
        for code_file in code_files:
            is_impacted = bool(impacted_files and code_file.path in impacted_files)
            # Pass use_llm=False to force fast rule-based + memory check
            task = asyncio.create_task(
                self._analyze_single_file_async(code_file, is_impacted, use_llm=False)
            )
            tasks.append((code_file.path, task))

        raw_contexts = {}
        for file_path, task in tasks:
            try:
                raw_contexts[file_path] = await task
            except Exception as e:
                logger.warning("rule_pass_failed", file=file_path, error=str(e))
                raw_contexts[file_path] = self._get_default_context(file_path)

        # STEP 2: Semantic Spread (Directory-based context propagation)
        # Group by directory to spread context from clear files to ambiguous ones
        dir_groups = {}
        for path_str, ctx_info in raw_contexts.items():
            dir_path = str(Path(path_str).parent)
            if dir_path not in dir_groups:
                dir_groups[dir_path] = []
            dir_groups[dir_path].append(ctx_info)

        from warden.analysis.domain.file_context import FileContext

        for dir_path, files in dir_groups.items():
            # Find dominant high-confidence context in this directory (excluding PRODUCTION default)
            clear_contexts = [f for f in files if f.confidence >= 0.85 and f.context != FileContext.PRODUCTION]

            if clear_contexts:
                # Use the most frequent clear context
                from collections import Counter
                dominant_ctx = Counter([f.context for f in clear_contexts]).most_common(1)[0][0]

                # Spread to low confidence files in the same directory
                for f in files:
                    if f.confidence < 0.7:
                        f.context = dominant_ctx
                        f.confidence = 0.8  # Boosted by semantic spread
                        f.detection_method += "+semantic_spread"
                        logger.debug("semantic_context_spread", file=f.file_path, context=dominant_ctx.value)

        # STEP 3: Batch LLM Analysis for remaining ambiguous files
        if self.llm_analyzer:
            # Collect files that still have low confidence
            ambiguous_items = []

            # Get project context from file analyzer
            p_ctx = self.file_analyzer.project_context if self.file_analyzer else None

            for path_str, ctx_info in raw_contexts.items():
                if ctx_info.confidence < 0.7:
                    # CONTEXT-AWARE SNIPER:
                    # Only send to LLM if file is critical for this project type
                    is_critical = True
                    if p_ctx:
                        is_critical = self._is_file_critical(path_str, p_ctx)

                    if is_critical:
                        # Prepare tuple for Batch analyzer: (Path, FileContext, float)
                        ambiguous_items.append((Path(path_str), ctx_info.context, ctx_info.confidence))
                    else:
                        logger.debug("skipping_llm_for_non_critical_file", file=path_str)

            if ambiguous_items:
                logger.info("batch_llm_enhancement_trigger", count=len(ambiguous_items))

                # Perform batch analysis (e.g. 10 files per LLM call)
                # LLM analyzer already has an internal batching mechanism
                try:
                    batch_results = await self.llm_analyzer.analyze_batch_async(ambiguous_items)

                    # Merge results back
                    for i, (path, _, _) in enumerate(ambiguous_items):
                        path_str = str(path)
                        if i < len(batch_results):
                            new_ctx, new_conf, method = batch_results[i]
                            raw_contexts[path_str].context = new_ctx
                            raw_contexts[path_str].confidence = new_conf
                            raw_contexts[path_str].detection_method = method
                except Exception as e:
                    logger.warning("batch_llm_enhancement_failed", error=str(e))

        return raw_contexts

    def _is_file_critical(self, file_path: str, project_context: ProjectContext) -> bool:
        """Check if file is critical based on project context and intelligence."""
        # CI OPTIMIZATION: Check intelligence risk level first
        if self.intelligence_loader and self.intelligence_loader.is_loaded:
            try:
                rel_path = str(Path(file_path).relative_to(self.project_root))
            except ValueError:
                rel_path = file_path

            risk_level = self.intelligence_loader.get_risk_for_file(rel_path)
            # P3 files are non-critical (utils, helpers, tests)
            if risk_level.value == "P3":
                logger.debug("file_marked_non_critical_by_intelligence", file=rel_path, risk="P3")
                return False
            # P0/P1 files are always critical
            if risk_level.value in ("P0", "P1"):
                logger.debug("file_marked_critical_by_intelligence", file=rel_path, risk=risk_level.value)
                return True

        # Fallback: Determine strict project type key for map
        p_type = "backend"  # Default fallback

        # Check explicit type first
        if project_context.project_type.value in ["mobile", "android", "ios"]:
            p_type = "mobile"
        elif project_context.project_type.value in ["web", "frontend"]:
            p_type = "web"
        # Check purpose keywords if generic
        elif project_context.purpose:
            purpose = project_context.purpose.lower()
            if "mobile" in purpose or "flutter" in purpose:
                p_type = "mobile"
            elif "frontend" in purpose or "react" in purpose:
                p_type = "web"

        patterns = CRITICALITY_MAP.get(p_type, CRITICALITY_MAP["backend"])

        # ALWAYS check backend criticals too (safety net for hybrid repos)
        all_patterns = patterns + CRITICALITY_MAP["backend"]

        return any(fnmatch.fnmatch(file_path, pattern) for pattern in all_patterns)

    async def _analyze_single_file_async(self, code_file: CodeFile, is_impacted: bool = False, use_llm: bool = True) -> Any:
        """
        Analyze a single file's context.

        Args:
            code_file: Code file to analyze
            is_impacted: Whether the file is impacted by a dependency change
            use_llm: Whether to use LLM for enhancement

        Returns:
            FileContextInfo for the file
        """
        # Run analysis in thread pool to avoid blocking
        asyncio.get_event_loop()

        # Calculate content hash (PRE-ANALYSIS step)
        content_hash = self._calculate_file_hash(code_file.content, code_file.path)

        # Populate CodeFile hash for downstream phases (Caching)
        code_file.hash = content_hash

        # Normalize path to relative for memory portability (CI vs Local)
        try:
            rel_path = str(Path(code_file.path).relative_to(self.project_root))
        except ValueError:
            # Fallback if path is not relative (e.g. symlinks outside root)
            rel_path = code_file.path

        # Check memory for existing state
        if self.config.get("trust_memory_context", True) and self.memory_manager and self.memory_manager._is_loaded:
            stored_state = self.memory_manager.get_file_state(rel_path)

            # If hash matches AND not impacted, mark as unchanged
            if stored_state and stored_state.get('content_hash') == content_hash and not is_impacted:
                # OPTIMIZATION: If we have stored context data, USE IT!
                # This skips the expensive FileContextAnalyzer step.
                context_data = stored_state.get('context_data')

                if context_data:
                    from warden.analysis.domain.file_context import FileContextInfo
                    try:
                        # Reconstruct FileContextInfo from stored dictionary
                        context_info = FileContextInfo.model_validate(context_data)

                        # Verify we have valid data (basic check)
                        if context_info.context:
                            context_info.is_unchanged = True
                            context_info.last_scan_timestamp = datetime.now()
                            # Ensure hash is set on the object
                            context_info.content_hash = content_hash

                            logger.debug("file_context_restored_from_memory", file=rel_path)
                            return context_info
                    except Exception as e:
                        logger.warning("context_restoration_failed", file=rel_path, error=str(e))
                        # Fallback to analysis on error matches
                        pass

        context_info = await self.file_analyzer.analyze_file_async(Path(code_file.path), use_llm=use_llm)

        # Enrich context info with hash and impact status
        context_info.content_hash = content_hash
        context_info.last_scan_timestamp = datetime.now()
        context_info.is_impacted = is_impacted

        # Determine if unchanged
        if self.memory_manager and self.memory_manager._is_loaded:
             stored_state = self.memory_manager.get_file_state(rel_path)
             if stored_state and stored_state.get('content_hash') == content_hash and not is_impacted:
                 context_info.is_unchanged = True
                 logger.debug("file_unchanged", file=rel_path)
             elif is_impacted:
                 context_info.is_unchanged = False
                 logger.info("dependency_impact_detected", file=rel_path)

        return context_info

    def _calculate_file_hash(self, content: str, file_path: str | None = None) -> str:
        """Calculate SHA-256 hash of file content. Uses normalization if enabled."""
        hashing_config = self.config.get("hashing", {})
        use_normalization = hashing_config.get("normalized", True)

        if use_normalization and file_path:
            lang = get_language_from_path(file_path)
            return NormalizedHasher.calculate_normalized_hash(content, lang)

        return hashlib.sha256(content.encode('utf-8')).hexdigest()

    def _get_default_context(self, file_path: str) -> Any:
        """
        Get default context for a file when analysis fails.

        Args:
            file_path: Path to the file

        Returns:
            Default FileContextInfo with production context
        """
        from warden.analysis.domain.file_context import ContextWeights, FileContextInfo

        return FileContextInfo(
            file_path=file_path,
            context=FileContext.PRODUCTION,
            confidence=0.0,
            detection_method="default",
            weights=ContextWeights(context=FileContext.PRODUCTION),
            suppressed_issues=[],
            suppression_reason="Analysis failed - using default production rules",
        )

    def _calculate_statistics(
        self,
        file_contexts: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Calculate statistics from file contexts.

        Args:
            file_contexts: Dictionary of file contexts

        Returns:
            Statistics dictionary
        """
        files_by_context = {}
        suppression_by_context = {}
        total_suppressions = 0

        for context_info in file_contexts.values():
            # Count files by context
            context_name = context_info.context.value
            files_by_context[context_name] = files_by_context.get(context_name, 0) + 1

            # Count suppressions
            if context_info.suppressed_issues:
                suppression_count = len(context_info.suppressed_issues)
                if suppression_count > 0:
                    total_suppressions += suppression_count
                    suppression_by_context[context_name] = suppression_by_context.get(context_name, 0) + suppression_count

        return {
            "files_by_context": files_by_context,
            "suppression_by_context": suppression_by_context,
            "total_suppressions": total_suppressions,
        }

    async def execute_with_weights_async(
        self,
        code_files: list[CodeFile],
        custom_weights: dict[str, dict[str, float]] | None = None
    ) -> PreAnalysisResult:
        """
        Execute PRE-ANALYSIS with custom weight configurations.

        Args:
            code_files: List of code files to analyze
            custom_weights: Optional custom weights per context

        Returns:
            PreAnalysisResult with custom weights applied
        """
        # Run standard analysis
        result = await self.execute_async(code_files)

        # Apply custom weights if provided
        if custom_weights:
            for _file_path, context_info in result.file_contexts.items():
                context_name = context_info.context.value
                if context_name in custom_weights:
                    # Update weights in context info
                    for metric, weight in custom_weights[context_name].items():
                        context_info.weights.weights[metric] = weight

            logger.info(
                "custom_weights_applied",
                contexts=list(custom_weights.keys()),
            )

        return result

    def get_suppression_summary(self, result: PreAnalysisResult) -> str:
        """
        Get human-readable summary of suppressions.

        Args:
            result: PreAnalysisResult to summarize

        Returns:
            Formatted suppression summary
        """
        if not result.suppression_by_context:
            return "No suppressions configured"

        summary_parts = []
        for context, count in sorted(result.suppression_by_context.items()):
            summary_parts.append(f"{context}: {count} suppressions")

        total = result.total_suppressions_configured
        summary = f"Total: {total} suppressions | " + " | ".join(summary_parts)

        return summary

    def should_skip_file(
        self,
        file_path: str,
        result: PreAnalysisResult
    ) -> bool:
        """
        Determine if a file should be skipped in analysis.

        Args:
            file_path: Path to check
            result: PreAnalysisResult with file contexts

        Returns:
            True if file should be skipped
        """
        if file_path not in result.file_contexts:
            return False  # Don't skip unknown files

        context_info = result.file_contexts[file_path]

        # Skip vendor and generated files
        if context_info.is_vendor or context_info.is_generated:
            logger.debug(
                "skipping_file",
                file=file_path,
                reason="vendor_or_generated",
            )
            return True

        # Skip documentation files
        if context_info.context == FileContext.DOCUMENTATION:
            logger.debug(
                "skipping_file",
                file=file_path,
                reason="documentation",
            )
            return True

        # Skip files with ignore markers
        if context_info.has_ignore_marker:
            logger.debug(
                "skipping_file",
                file=file_path,
                reason="ignore_marker",
            )
            return True

        if context_info.has_ignore_marker:
            logger.debug(
                "skipping_file",
                file=file_path,
                reason="ignore_marker",
            )
            return True

        return False

    def _enrich_context_from_memory(self, context: ProjectContext) -> None:
        """Enrich project context with facts from memory."""
        # Restore project purpose and architecture
        purpose_data = self.memory_manager.get_project_purpose()
        if purpose_data:
            context.purpose = purpose_data.get("purpose", "")
            context.architecture_description = purpose_data.get("architecture_description", "")
            logger.info("project_purpose_restored_from_memory", purpose_preview=context.purpose[:50], source="memory_manager")

        # Load service abstractions from memory if not detected in current run
        # (or merge with detected ones)
        memory_abstractions = self.memory_manager.get_service_abstractions()

        for fact in memory_abstractions:
            if fact.metadata and fact.subject not in context.service_abstractions:
                # Restore abstraction from memory
                context.service_abstractions[fact.subject] = fact.metadata
                logger.debug("service_abstraction_restored_from_memory", service=fact.subject)

    async def _save_context_to_memory_async(self, context: ProjectContext) -> None:
        """Save project context facts to memory."""
        # Save project purpose
        if context.purpose:
            self.memory_manager.update_project_purpose(
                context.purpose,
                context.architecture_description
            )

        # Save service abstractions
        if hasattr(context, 'service_abstractions'):
            for abstraction in context.service_abstractions.values():
                self.memory_manager.store_service_abstraction(abstraction)

            # Persist to disk
            await self.memory_manager.save_async()
    async def save_file_states_async(self, file_contexts: dict[str, Any]) -> None:
        """
        Save current file states to memory.
        """
        for path, info in file_contexts.items():
            if info.content_hash:
                # Normalize path for saving
                try:
                    rel_path = str(Path(path).relative_to(self.project_root))
                except ValueError:
                    rel_path = path

                logger.debug("saving_file_state", file=rel_path, hash=info.content_hash)

                # OPTIMIZATION: Save the full context info so we can restore it later
                context_data = info.to_json()

                self.memory_manager.update_file_state(
                    file_path=rel_path,
                    content_hash=info.content_hash,
                    findings_count=0,
                    context_data=context_data
                )

        await self.memory_manager.save_async()

    # Stable version for analysis logic (bump this when logic changes)
    ANALYSIS_LOGIC_VERSION = "1.0.0"

    def _calculate_environment_hash(self) -> str:
        """
        Calculate a hash representing the current environment state.
        Includes: Analysis Logic Version, Config Content, Rules Content.
        """
        # Use stable logic version instead of package __version__ to avoid
        # invalidating cache on every commit/tag bump.
        components = [self.ANALYSIS_LOGIC_VERSION]

        # Add config content
        config_files = [".warden/config.yaml", ".warden/rules.yaml", ".warden/warden.yaml"]
        for cf in config_files:
            p = self.project_root / cf
            if p.exists():
                try:
                    with open(p, encoding="utf-8") as f:
                        content = f.read()
                        # Optimization: Remove comments and whitespace to avoid invalidating cache
                        # on non-functional changes
                        content = re.sub(r'#.*$', '', content, flags=re.MULTILINE)
                        content = "".join(content.split())
                        components.append(hashlib.md5(content.encode()).hexdigest())
                except (ValueError, TypeError, AttributeError):  # Non-critical metrics
                    pass

        # Add internal config dict hash (if passed via CLI args etc)
        if self.config:
            import json
            try:
                # Deterministic JSON representation
                components.append(json.dumps(self.config, sort_keys=True, default=str))
            except Exception:
                # Fallback to str if not json serializable
                components.append(str(self.config))

        return hashlib.sha256("-".join(components).encode()).hexdigest()

    def _validate_environment_hash(self) -> bool:
        """Check if current environment matches stored memory."""
        if not self.memory_manager or not self.memory_manager._is_loaded:
            return False

        stored_hash = self.memory_manager.get_environment_hash()
        return stored_hash == self.env_hash

    async def _identify_impacted_files_async(self, code_files: list[CodeFile], project_context: ProjectContext) -> set[str]:
        """
        Identify files impacted by changes in their dependencies.

        Args:
            code_files: All code files in the project
            project_context: Metadata for dependency resolution

        Returns:
            Set of absolute paths of impacted files
        """
        logger.info("dependency_impact_analysis_started")

        # 1. Initialize DependencyGraph
        self.dependency_graph = DependencyGraph(self.project_root, project_context, self.ast_registry)

        # AST providers are already loaded in step 2.5

        # 2. Build Graph (Scan all files for dependencies)
        # This is relatively fast with AST providers
        scan_tasks = []
        for cf in code_files:
            lang = self._guess_language_by_extension(cf.path)
            scan_tasks.append(self.dependency_graph.scan_file_async(Path(cf.path), lang))

        await asyncio.gather(*scan_tasks)

        # 3. Identify physically changed files
        changed_physically = []
        for cf in code_files:
            content_hash = self._calculate_file_hash(cf.content, cf.path)
            rel_path = str(Path(cf.path).relative_to(self.project_root))

            # Check memory for existing state
            if self.memory_manager and self.memory_manager._is_loaded:
                stored_state = self.memory_manager.get_file_state(rel_path)
                if not stored_state or stored_state.get('content_hash') != content_hash:
                    changed_physically.append(Path(cf.path))
            else:
                # If no memory, we assume all files are "changed" for graph purposes
                changed_physically.append(Path(cf.path))

        if not changed_physically:
            return set()

        # 4. Traversal: Calculate transitive impact
        impacted = self.dependency_graph.get_transitive_impact(changed_physically)

        impacted_paths = {str(p) for p in impacted}

        if impacted_paths:
            logger.info(
                "transitive_impact_calculated",
                changed_files_count=len(changed_physically),
                impacted_files_count=len(impacted_paths)
            )

        return impacted_paths

    def _guess_language_by_extension(self, file_path: str) -> CodeLanguage:
        """Guess language by file extension using centralized utility."""
        from warden.shared.utils.language_utils import get_language_from_path
        return get_language_from_path(file_path)
