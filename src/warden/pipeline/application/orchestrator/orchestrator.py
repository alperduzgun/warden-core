"""
Main Phase Orchestrator for 6-phase pipeline.

Coordinates execution of all pipeline phases with shared PipelineContext.
"""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable
from uuid import uuid4

from warden.pipeline.domain.pipeline_context import PipelineContext
from warden.pipeline.domain.models import (
    PipelineResult,
    ValidationPipeline,
    PipelineConfig,
)
from warden.pipeline.domain.enums import PipelineStatus
from warden.rules.application.rule_validator import CustomRuleValidator
from warden.validation.domain.frame import CodeFile, ValidationFrame
from warden.shared.infrastructure.logging import get_logger

from .phase_executor import PhaseExecutor
from .frame_executor import FrameExecutor
from warden.shared.services.semantic_search_service import SemanticSearchService

logger = get_logger(__name__)


class PhaseOrchestrator:
    """
    Orchestrates the complete 6-phase validation pipeline.

    Phases:
    0. PRE-ANALYSIS: Project/file understanding
    1. ANALYSIS: Quality metrics calculation
    2. CLASSIFICATION: Frame selection & suppression
    3. VALIDATION: Execute validation frames
    4. FORTIFICATION: Generate security fixes
    5. CLEANING: Suggest quality improvements
    """

    def __init__(
        self,
        frames: Optional[List[ValidationFrame]] = None,
        config: Optional[PipelineConfig] = None,
        progress_callback: Optional[Callable] = None,
        project_root: Optional[Path] = None,
        llm_service: Optional[Any] = None,
        available_frames: Optional[List[ValidationFrame]] = None,
    ):
        """
        Initialize phase orchestrator.

        Args:
            frames: List of validation frames to execute (User configured)
            config: Pipeline configuration (can be dict or PipelineConfig)
            progress_callback: Optional callback for progress updates
            project_root: Root directory of the project
            llm_service: Optional LLM service for AI-powered phases
            available_frames: List of all discoverable frames (for AI selection)
        """
        self.frames = frames or []
        self.available_frames = available_frames or self.frames  # Fallback to frames if not provided

        # Handle both dict and PipelineConfig for backward compatibility
        if config is None:
            self.config = PipelineConfig()
        elif isinstance(config, dict):
            # Convert dict to PipelineConfig
            self.config = PipelineConfig()
            for key, value in config.items():
                setattr(self.config, key, value)
        else:
            self.config = config

        self._progress_callback = progress_callback
        self.project_root = project_root or Path.cwd()
        self.llm_service = llm_service

        # Initialize rule validator if global rules exist
        self.rule_validator = None
        if self.config.global_rules:
            self.rule_validator = CustomRuleValidator(self.config.global_rules)

        # Initialize Semantic Search Service if enabled in config
        self.semantic_search_service = None
        ss_config = getattr(self.config, 'semantic_search_config', None)
        if ss_config and ss_config.get("enabled", False):
            # Pass project root for relative path calculations in indexing
            ss_config["project_root"] = str(self.project_root)
            self.semantic_search_service = SemanticSearchService(ss_config)

        # Initialize phase executor
        self.phase_executor = PhaseExecutor(
            config=self.config,
            progress_callback=self.progress_callback,
            project_root=self.project_root,
            llm_service=self.llm_service,
            # Validation logic needs all available frames for AI selection
            frames=self.available_frames,
            semantic_search_service=self.semantic_search_service
        )

        # Initialize frame executor
        self.frame_executor = FrameExecutor(
            frames=self.frames,  # User configured frames (default fallback)
            config=self.config,
            progress_callback=self.progress_callback,
            rule_validator=self.rule_validator,
            llm_service=self.llm_service,
            available_frames=self.available_frames, # All available frames for lookup
            semantic_search_service=self.semantic_search_service
        )

        # Sort frames by priority
        self._sort_frames_by_priority()

        logger.info(
            "phase_orchestrator_initialized",
            project_root=str(self.project_root),
            frame_count=len(self.frames),
            strategy=self.config.strategy.value if self.config.strategy else "sequential",
            frame_rules_count=len(self.config.frame_rules) if self.config.frame_rules else 0,
        )

    @property
    def progress_callback(self) -> Optional[Callable]:
        """Get progress callback."""
        return self._progress_callback

    @progress_callback.setter
    def progress_callback(self, value: Optional[Callable]) -> None:
        """Set progress callback and propagate to executors."""
        self._progress_callback = value
        if hasattr(self, 'phase_executor'):
            self.phase_executor.progress_callback = value
        if hasattr(self, 'frame_executor'):
            self.frame_executor.progress_callback = value

    def _sort_frames_by_priority(self) -> None:
        """Sort frames by priority value (lower value = higher priority)."""
        if self.frames:
            self.frames.sort(key=lambda f: f.priority.value if hasattr(f, 'priority') else 999)

    async def execute(
        self,
        code_files: List[CodeFile],
        frames_to_execute: Optional[List[str]] = None,
    ) -> tuple[PipelineResult, PipelineContext]:
        """
        Execute the complete 6-phase pipeline with shared context.
        Compatible with old orchestrator interface.

        Args:
            code_files: List of code files to process
            frames_to_execute: Optional list of frame IDs to execute (overrides classification)

        Returns:
            Tuple of (PipelineResult, PipelineContext)
        """
        context = await self.execute_pipeline_async(code_files, frames_to_execute)

        # Build PipelineResult from context for compatibility
        result = self._build_pipeline_result(context)

        return result, context

    async def execute_pipeline_async(
        self,
        code_files: List[CodeFile],
        frames_to_execute: Optional[List[str]] = None,
    ) -> PipelineContext:
        """
        Execute the complete 6-phase pipeline with shared context.

        Args:
            code_files: List of code files to process
            frames_to_execute: Optional list of frame IDs to execute (overrides classification)

        Returns:
            PipelineContext with results from results of all phases
        """
        language = "unknown"
        if code_files and len(code_files) > 0:
            language = code_files[0].language or "unknown"
            if language == "unknown" and code_files[0].path:
                # Simple fallback detection
                ext = Path(code_files[0].path).suffix.lower()
                if ext == ".py": language = "python"
                elif ext in [".ts", ".tsx"]: language = "typescript"
                elif ext in [".js", ".jsx"]: language = "javascript"
                elif ext == ".go": language = "go"
                elif ext == ".java": language = "java"
                elif ext == ".cs": language = "csharp"

        # Initialize shared context
        context = PipelineContext(
            pipeline_id=str(uuid4()),
            started_at=datetime.now(),
            file_path=Path(code_files[0].path) if code_files else Path.cwd(),
            project_root=self.project_root, # Pass from orchestrator
            use_gitignore=getattr(self.config, 'use_gitignore', True),
            source_code=code_files[0].content if code_files else "",
            language=language,
        )

        # Create pipeline entity
        self.pipeline = ValidationPipeline(
            id=context.pipeline_id,
            status=PipelineStatus.RUNNING,
            started_at=context.started_at,
        )

        logger.info(
            "pipeline_execution_started",
            pipeline_id=context.pipeline_id,
            file_count=len(code_files),
            frames_override=frames_to_execute,
        )

        if self.progress_callback:
            self.progress_callback("pipeline_started", {
                "pipeline_id": context.pipeline_id,
                "file_count": len(code_files),
            })

        try:
            # Phase 0: PRE-ANALYSIS
            if self.config.enable_pre_analysis:
                await self.phase_executor.execute_pre_analysis_async(context, code_files)

            # Phase 1: ANALYSIS
            if getattr(self.config, 'enable_analysis', True):
                await self.phase_executor.execute_analysis_async(context, code_files)
                # Initialize after score to before score
                context.quality_score_after = context.quality_score_before

            # Phase 2: CLASSIFICATION
            # If frames override is provided, use it and skip AI classification
            if frames_to_execute:
                context.selected_frames = frames_to_execute
                context.classification_reasoning = "User manually selected frames via CLI"
                logger.info("using_frame_override", selected_frames=frames_to_execute)
                
                # Add phase result placeholder
                context.add_phase_result("CLASSIFICATION", {
                    "selected_frames": frames_to_execute,
                    "suppression_rules_count": 0,
                    "reasoning": "Manual override",
                    "skipped": True
                })
                
                if self.progress_callback:
                    self.progress_callback("phase_skipped", {
                        "phase": "CLASSIFICATION",
                        "reason": "manual_frame_override"
                    })
            else:
                # Classification is critical for intelligent frame selection
                logger.info("phase_enabled", phase="CLASSIFICATION", enabled=True, enforced=True)
                await self.phase_executor.execute_classification_async(context, code_files)

            # Phase 3: VALIDATION with execution strategies
            enable_validation = getattr(self.config, 'enable_validation', True)
            if enable_validation:
                logger.info("phase_enabled", phase="VALIDATION", enabled=enable_validation)
                # Pass pipeline reference to frame executor
                await self.frame_executor.execute_validation_with_strategy_async(
                    context, code_files, self.pipeline
                )
            else:
                logger.info("phase_skipped", phase="VALIDATION", reason="disabled_in_config")
                if self.progress_callback:
                    self.progress_callback("phase_skipped", {
                        "phase": "VALIDATION",
                        "phase_name": "VALIDATION",
                        "reason": "disabled_in_config"
                    })

            # Phase 4: FORTIFICATION
            enable_fortification = getattr(self.config, 'enable_fortification', True)
            if enable_fortification:
                logger.info("phase_enabled", phase="FORTIFICATION", enabled=enable_fortification)
                await self.phase_executor.execute_fortification_async(context, code_files)
            else:
                logger.info("phase_skipped", phase="FORTIFICATION", reason="disabled_in_config")
                if self.progress_callback:
                    self.progress_callback("phase_skipped", {
                        "phase": "FORTIFICATION",
                        "phase_name": "FORTIFICATION",
                        "reason": "disabled_in_config"
                    })

            # Phase 5: CLEANING
            enable_cleaning = getattr(self.config, 'enable_cleaning', True)
            if enable_cleaning:
                logger.info("phase_enabled", phase="CLEANING", enabled=enable_cleaning)
                await self.phase_executor.execute_cleaning_async(context, code_files)
            else:
                logger.info("phase_skipped", phase="CLEANING", reason="disabled_in_config")
                if self.progress_callback:
                    self.progress_callback("phase_skipped", {
                        "phase": "CLEANING",
                        "phase_name": "CLEANING",
                        "reason": "disabled_in_config"
                    })

            # Post-Process: Apply Baseline (Smart Filter)
            self._apply_baseline(context)

            # Update pipeline status based on results
            has_errors = len(context.errors) > 0
            if has_errors:
                logger.warning("pipeline_has_errors", count=len(context.errors), errors=context.errors[:5])
            
            if self.pipeline.frames_failed > 0 or has_errors:
                # Only fail if there are actual failures or blocker violations
                if (has_errors) or (self.pipeline.frames_failed > 0) or any(
                    fr.get('result').is_blocker for fr in getattr(context, 'frame_results', {}).values() 
                    if fr.get('result') and fr.get('result').status == "failed"
                ):
                    self.pipeline.status = PipelineStatus.FAILED
                else:
                    self.pipeline.status = PipelineStatus.COMPLETED
            else:
                self.pipeline.status = PipelineStatus.COMPLETED
                
            self.pipeline.completed_at = datetime.now()

            logger.info(
                "pipeline_execution_completed",
                pipeline_id=context.pipeline_id,
                summary=context.get_summary(),
            )

        except RuntimeError as e:
            if "Integrity check failed" in str(e):
                logger.error("integrity_check_failed", error=str(e))
                self.pipeline.status = PipelineStatus.FAILED
                context.errors.append(str(e))
                # Add a dummy result so CLI can show it
                return context
            raise e
            
        except Exception as e:
            # Global pipeline failure handler - ensures status is updated and error is traced.
            # While generic, this is necessary at the top orchestration level to catch any phase failure.
            import traceback
            self.pipeline.status = PipelineStatus.FAILED
            self.pipeline.completed_at = datetime.now()
            logger.error(
                "pipeline_execution_failed",
                pipeline_id=context.pipeline_id,
                error=str(e),
                error_type=type(e).__name__,
                traceback=traceback.format_exc(),
            )
            context.errors.append(f"Pipeline failed: {str(e)}")
            raise

        return context

    def _apply_baseline(self, context: PipelineContext) -> None:
        """Filter out existing issues present in baseline."""
        import json
        baseline_path = self.project_root / ".warden" / "baseline.json"
        
        # Only apply if baseline exists and NOT in 'strict' mode (unless configured otherwise)
        if not baseline_path.exists():
            return
            
        settings = getattr(self.config, 'settings', {})
        if settings.get('mode') == 'strict' and not settings.get('use_baseline_in_strict', False):
            # In strict mode, we might want to ignore baseline and show everything
            # But usually baseline implies "Acceptance", so default should be to use it unless disabled.
            pass

        try:
            with open(baseline_path) as f:
                baseline_data = json.load(f)
            
            # Extract baseline fingerprints (rule_id + file_path)
            known_issues = set()
            for frame_res in baseline_data.get('frame_results', []):
                for finding in frame_res.get('findings', []):
                    # Robust identification: rule_id + file (relative to root)
                    rid = finding.get('rule_id') if isinstance(finding, dict) else getattr(finding, 'rule_id', None)
                    fpath = finding.get('file_path') if isinstance(finding, dict) else getattr(finding, 'path', finding.get('path'))
                    
                    if not fpath: continue
                    
                    # Normalize path relative to project root
                    try:
                        abs_path = Path(fpath)
                        if not abs_path.is_absolute():
                            abs_path = self.project_root / fpath
                        rel_path = str(abs_path.resolve().relative_to(self.project_root.resolve()))
                    except: 
                        rel_path = str(fpath) # Fallback
                    
                    if rid:
                        known_issues.add(f"{rid}:{rel_path}")

            if not known_issues:
                return
            
            logger.info("baseline_loaded", known_issues_count=len(known_issues))

            # Filter current findings in Frame Results
            total_suppressed = 0
            
            for fid, f_res in context.frame_results.items():
                result_obj = f_res.get('result') # FrameResult object
                if not result_obj: continue
                
                filtered_findings = []
                # Keep track of suppressions
                suppressed_in_frame = 0
                
                # Findings might be objects or dicts
                current_findings = result_obj.findings
                if not current_findings: continue
                
                for finding in current_findings:
                    rid = getattr(finding, 'rule_id', getattr(finding, 'check_id', None))
                    fpath = getattr(finding, 'file_path', getattr(finding, 'path', str(context.file_path)))
                    
                    # Normalize current finding path
                    try:
                        abs_path = Path(fpath)
                        if not abs_path.is_absolute():
                            abs_path = self.project_root / fpath
                        rel_path = str(abs_path.resolve().relative_to(self.project_root.resolve()))
                    except:
                        rel_path = str(fpath)

                    key = f"{rid}:{rel_path}"
                    
                    if key in known_issues:
                        suppressed_in_frame += 1
                        total_suppressed += 1
                        # We suppress it from active findings
                    else:
                        filtered_findings.append(finding)
                
                # Update frame result
                result_obj.findings = filtered_findings
                
                # Update status if all findings suppressed
                if not filtered_findings and result_obj.status == "failed":
                    result_obj.status = "passed"
                    # Also unmark is_blocker?
                    # result_obj.is_blocker = False 
            
            if total_suppressed > 0:
                logger.info("baseline_applied", suppressed_issues=total_suppressed)
                
                # Sync context.findings to reflect suppression
                # Re-aggregate from frames
                all_findings = []
                for f_res in context.frame_results.values():
                    res = f_res.get('result')
                    if res and res.findings:
                        all_findings.extend(res.findings)
                context.findings = all_findings

        except Exception as e:
            logger.warning("baseline_application_failed", error=str(e))

    def _build_pipeline_result(self, context: PipelineContext) -> PipelineResult:
        """Build PipelineResult from context for compatibility."""
        frame_results = []

        # Convert context frame results to FrameResult objects
        if hasattr(context, 'frame_results') and context.frame_results:
            for frame_id, frame_data in context.frame_results.items():
                result = frame_data.get('result')
                if result:
                    frame_results.append(result)

        # Helper to get severity from finding (object or dict)
        def get_severity(f: Any) -> str:
            val = None
            if isinstance(f, dict):
                val = f.get('severity')
            else:
                val = getattr(f, 'severity', None)
            
            
            
            return str(val).lower() if val else ''

        # Calculate finding counts
        findings = context.findings if hasattr(context, 'findings') else []
        critical_findings = len([f for f in findings if get_severity(f) == 'critical'])
        high_findings = len([f for f in findings if get_severity(f) == 'high'])
        medium_findings = len([f for f in findings if get_severity(f) == 'medium'])
        low_findings = len([f for f in findings if get_severity(f) == 'low'])
        total_findings = len(findings)

        # Calculate quality score if not present or default
        quality_score = getattr(context, 'quality_score_before', None)
        


        if quality_score is None or quality_score == 0.0:
            # Formula: Asymptotic decay using shared utility
            from warden.shared.utils.quality_calculator import calculate_quality_score
            quality_score = calculate_quality_score(findings)

        # Sync back to context for summary reporting
        context.quality_score_after = quality_score

        # Calculate actual frames processed based on execution results
        frames_passed = getattr(self.pipeline, 'frames_passed', 0) if hasattr(self, 'pipeline') else 0
        frames_failed = getattr(self.pipeline, 'frames_failed', 0) if hasattr(self, 'pipeline') else 0
        frames_skipped = 0 
        
        actual_total = frames_passed + frames_failed + frames_skipped
        planned_total = len(getattr(context, 'selected_frames', [])) or len(self.frames)
        
        # Ensure total never shows less than what was actually processed/passed
        total_frames = max(actual_total, planned_total)

        return PipelineResult(
            pipeline_id=context.pipeline_id,
            pipeline_name="Validation Pipeline",
            status=self.pipeline.status if hasattr(self, 'pipeline') else PipelineStatus.COMPLETED,
            duration=(datetime.now() - context.started_at).total_seconds() if context.started_at else 0.0,
            total_frames=total_frames,
            frames_passed=frames_passed,
            frames_failed=frames_failed,
            frames_skipped=frames_skipped,
            total_findings=total_findings,
            critical_findings=critical_findings,
            high_findings=high_findings,
            medium_findings=medium_findings,
            low_findings=low_findings,

            frame_results=frame_results,
            # Populate metadata
            metadata={
                "strategy": self.config.strategy.value,
                "fail_fast": self.config.fail_fast,
                "frame_executions": [
                    {
                        "frame_id": fe.frame_id,
                        "status": fe.status,
                        "duration": fe.duration
                    } for fe in getattr(self.pipeline, 'frame_executions', [])
                ]
            },
            # Populate new fields
            artifacts=getattr(context, 'artifacts', []),
            quality_score=quality_score,
            # LLM Usage
            total_tokens=getattr(context, 'total_tokens', 0),
            prompt_tokens=getattr(context, 'prompt_tokens', 0),
            completion_tokens=getattr(context, 'completion_tokens', 0),
        )