"""
PRE-ANALYSIS Phase Orchestrator.

Phase 0 of the 6-phase pipeline that analyzes project structure and file contexts
to enable context-aware analysis and false positive prevention.
"""

import asyncio
import time
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable, Set
import structlog
import hashlib
from datetime import datetime
from warden.analysis.application.integrity_scanner import IntegrityScanner, IntegrityIssue

from warden.analysis.domain.file_context import (
    FileContext,
    PreAnalysisResult,
)
from warden.analysis.domain.project_context import ProjectContext
from warden.analysis.application.project_structure_analyzer import ProjectStructureAnalyzer
from warden.analysis.application.file_context_analyzer import FileContextAnalyzer
from warden.memory.application.memory_manager import MemoryManager
from warden.analysis.application.project_purpose_detector import ProjectPurposeDetector
from warden.ast.application.provider_registry import ASTProviderRegistry
from warden.ast.application.provider_loader import ASTProviderLoader
from warden.analysis.application.dependency_graph import DependencyGraph
from warden.ast.domain.enums import CodeLanguage
from warden.validation.domain.frame import CodeFile

logger = structlog.get_logger()


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
        progress_callback: Optional[Callable] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Initialize PRE-ANALYSIS phase.

        Args:
            project_root: Root directory of the project
            progress_callback: Optional callback for progress updates
            config: Optional configuration including LLM settings
        """
        self.project_root = Path(project_root)
        self.progress_callback = progress_callback
        self.config = config or {}

        # Initialize analyzers
        self.project_analyzer = ProjectStructureAnalyzer(self.project_root, self.config.get("llm_config"))
        self.file_analyzer: Optional[FileContextAnalyzer] = None  # Created after project analysis
        self.llm_analyzer = None  # Will be initialized if enabled
        
        self.memory_manager = MemoryManager(self.project_root)
        self.env_hash = self._calculate_environment_hash()

        # AST and Dependency Infrastructure
        self.ast_registry = ASTProviderRegistry()
        self.ast_loader = ASTProviderLoader(self.ast_registry)
        self.dependency_graph: Optional[DependencyGraph] = None  # Initialized in execute
        self.integrity_scanner = IntegrityScanner(self.project_root, self.ast_registry, self.config.get("integrity_config"))

    async def execute(
        self, 
        code_files: List[CodeFile], 
        pipeline_context: Optional[Any] = None
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
            await self._initialize_llm_analyzer()
            
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
            project_context = await self._analyze_project_structure(project_context)

            # Ensure AST providers are loaded for integrity check
            await self.ast_loader.load_all()

            # Step 2.5: Integrity Check (Fail-Fast)
            # Scan files for syntax validity and optional build verification
            # Pass pipeline_context to enable AST caching for DRY principle
            integrity_issues = await self.integrity_scanner.scan(code_files, project_context, pipeline_context)
            if integrity_issues:
                # Log issues
                for issue in integrity_issues:
                    logger.error("integrity_check_failure", file=issue.file_path, error=issue.message)
                
                # Check for critical failures (syntax errors or build failures)
                # We consider any integrity issue as critical for now if fail_fast is enabled or by default
                fail_fast = self.config.get("integrity_config", {}).get("fail_fast", True)
                if fail_fast:
                    logger.error("integrity_check_failed_aborting", issue_count=len(integrity_issues))
                    raise RuntimeError(f"Integrity check failed with {len(integrity_issues)} issues. Fix syntax/build errors before running Warden.")

            # Step 3: Dependency Awareness (Impact Analysis)
            impacted_files = await self._identify_impacted_files(code_files, project_context)

            # Step 4: Initialize file analyzer with project context and LLM
            self.file_analyzer = FileContextAnalyzer(project_context, self.llm_analyzer)

            # Step 5: Analyze file contexts in parallel
            file_contexts = await self._analyze_file_contexts(code_files, impacted_files)

            # Step 5: Calculate statistics
            statistics = self._calculate_statistics(file_contexts)

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
            await self._save_context_to_memory(project_context)
            
            # Step 7: Save file states (hashes)
            # We save this now so next run knows about these hashes
            await self.save_file_states(file_contexts)
            
            # Step 8: Save current environment hash
            if self.memory_manager and self.memory_manager._is_loaded:
                self.memory_manager.update_environment_hash(self.env_hash)
                await self.memory_manager.save_async()

            # Step 9: Trigger Semantic Indexing (Smart Incremental)
            try:
                # Import here to avoid circular dependencies
                from warden.shared.services.semantic_search_service import SemanticSearchService
                ss_config = self.config.get("semantic_search", {})
                ss_service = SemanticSearchService(ss_config)
                
                if ss_service.is_available():
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

    async def _initialize_llm_analyzer(self) -> None:
        """Initialize LLM analyzer if enabled in config."""
        # Check for use_llm in config - it should be directly in config dict
        use_llm = self.config.get("use_llm", True)  # Default to True if not specified

        if not use_llm:
            logger.info("llm_disabled_for_pre_analysis")
            return

        try:
            from warden.analysis.application.llm_context_analyzer import LlmContextAnalyzer
            from warden.llm.config import load_llm_config_async

            # Load LLM configuration
            llm_config = await load_llm_config_async()

            # Get PRE-ANALYSIS specific config
            pre_analysis_config = self.config.get("pre_analysis", {})
            confidence_threshold = pre_analysis_config.get("llm_threshold", 0.7)
            batch_size = pre_analysis_config.get("batch_size", 10)

            # Initialize LLM analyzer
            self.llm_analyzer = LlmContextAnalyzer(
                llm_config=llm_config,
                confidence_threshold=confidence_threshold,
                batch_size=batch_size,
                cache_enabled=True,
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

    async def _analyze_project_structure(self, initial_context: Optional[ProjectContext] = None) -> ProjectContext:
        """
        Analyze project structure and characteristics.

        Returns:
            ProjectContext with detected information
        """
        logger.info("analyzing_project_structure")

        # Run project structure analysis
        project_context = await self.project_analyzer.analyze_async(initial_context)

        # Step 2.1: Semantic Discovery (Purpose and Architecture)
        # Check if we already have it in memory via enrichment (called in execute)
        if not project_context.purpose and self.llm_analyzer:
            detector = ProjectPurposeDetector(self.project_root, self.config.get("llm_config"))
            # We need the file list for discovery canvas
            # Convert Path objects to list
            all_files = list(self.project_root.rglob("*"))
            purpose, arch = await detector.detect_async(
                all_files, 
                project_context.config_files
            )
            project_context.purpose = purpose
            project_context.architecture_description = arch
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

    async def _analyze_file_contexts(
        self,
        code_files: List[CodeFile],
        impacted_files: Set[str] = None
    ) -> Dict[str, Any]:
        """
        Analyze context for each file.

        Args:
            code_files: List of code files to analyze

        Returns:
            Dictionary mapping file paths to FileContextInfo
        """
        logger.info(
            "analyzing_file_contexts",
            file_count=len(code_files),
        )

        # Create tasks for parallel analysis
        tasks = []
        for code_file in code_files:
            is_impacted = bool(impacted_files and code_file.path in impacted_files)
            task = asyncio.create_task(
                self._analyze_single_file(code_file, is_impacted)
            )
            tasks.append((code_file.path, task))

        # Wait for all analyses to complete
        file_contexts = {}
        for file_path, task in tasks:
            try:
                context_info = await task
                file_contexts[file_path] = context_info
            except Exception as e:
                logger.warning(
                    "file_context_analysis_failed",
                    file=file_path,
                    error=str(e),
                )
                # Use default production context on failure
                file_contexts[file_path] = self._get_default_context(file_path)

        return file_contexts

    async def _analyze_single_file(self, code_file: CodeFile, is_impacted: bool = False) -> Any:
        """
        Analyze a single file's context.

        Args:
            code_file: Code file to analyze

        Returns:
            FileContextInfo for the file
        """
        # Run analysis in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        
        # Calculate content hash (PRE-ANALYSIS step)
        content_hash = self._calculate_file_hash(code_file.content)
        
        # Normalize path to relative for memory portability (CI vs Local)
        try:
            rel_path = str(Path(code_file.path).relative_to(self.project_root))
        except ValueError:
            # Fallback if path is not relative (e.g. symlinks outside root)
            rel_path = code_file.path

        # Check memory for existing state
        if self.trust_memory_context and self.memory_manager and self.memory_manager._is_loaded:
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

        context_info = await loop.run_in_executor(
            None,
            self.file_analyzer.analyze_file,
            Path(code_file.path)
        )
        
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

    def _calculate_file_hash(self, content: str) -> str:
        """Calculate SHA-256 hash of file content."""
        return hashlib.sha256(content.encode('utf-8')).hexdigest()

    def _get_default_context(self, file_path: str) -> Any:
        """
        Get default context for a file when analysis fails.

        Args:
            file_path: Path to the file

        Returns:
            Default FileContextInfo with production context
        """
        from warden.analysis.domain.file_context import FileContextInfo, ContextWeights

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
        file_contexts: Dict[str, Any]
    ) -> Dict[str, Any]:
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

    async def execute_with_weights(
        self,
        code_files: List[CodeFile],
        custom_weights: Optional[Dict[str, Dict[str, float]]] = None
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
        result = await self.execute(code_files)

        # Apply custom weights if provided
        if custom_weights:
            for file_path, context_info in result.file_contexts.items():
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
            logger.info("project_purpose_restored_from_memory")

        # Load service abstractions from memory if not detected in current run
        # (or merge with detected ones)
        memory_abstractions = self.memory_manager.get_service_abstractions()
        
        for fact in memory_abstractions:
            if fact.metadata and fact.subject not in context.service_abstractions:
                # Restore abstraction from memory
                context.service_abstractions[fact.subject] = fact.metadata
                logger.debug("service_abstraction_restored_from_memory", service=fact.subject)

    async def _save_context_to_memory(self, context: ProjectContext) -> None:
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
    async def save_file_states(self, file_contexts: Dict[str, Any]) -> None:
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
                    with open(p, "rb") as f:
                        components.append(hashlib.md5(f.read()).hexdigest())
                except Exception:
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

    async def _identify_impacted_files(self, code_files: List[CodeFile], project_context: ProjectContext) -> Set[str]:
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
            content_hash = self._calculate_file_hash(cf.content)
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
