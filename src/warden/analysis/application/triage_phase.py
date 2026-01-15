"""
TRIAGE Phase Orchestrator (Phase 0.5).
Executes the Adaptive Hybrid Triage strategy.
"""

import asyncio
import time
from typing import List, Dict, Any, Optional, Callable
import structlog
from pathlib import Path


from warden.validation.domain.frame import CodeFile
from warden.pipeline.domain.pipeline_context import PipelineContext
from warden.analysis.application.triage_service import TriageService
from warden.analysis.domain.triage_models import TriageDecision, TriageLane, RiskScore
from warden.llm.factory import create_client

logger = structlog.get_logger()

class TriagePhase:
    """
    Executes Adaptive Hybrid Triage.
    Routes files to Fast/Middle/Deep lanes based on risk scores.
    """
    
    def __init__(
        self,
        project_root: Path,
        progress_callback: Optional[Callable] = None,
        config: Optional[Dict[str, Any]] = None,
        llm_service: Optional[Any] = None
    ):
        self.project_root = project_root
        self.progress_callback = progress_callback
        self.config = config or {}
        
        # Use provided LLM service or create new one (Local/Fast pref)
        self.llm_service = llm_service or create_client()
        self.triage_service = TriageService(self.llm_service)
        
    async def execute_async(
        self,
        code_files: List[CodeFile],
        pipeline_context: PipelineContext
    ) -> Dict[str, Any]:
        """Execute Triage phase."""
        start_time = time.perf_counter()
        logger.info("triage_phase_started", file_count=len(code_files))
        
        if self.progress_callback:
            self.progress_callback("triage_started", {"total_files": len(code_files)})

        decisions = {}
        
        # Use Batch Processing
        logger.info("triage_batch_processing_started", total_files=len(code_files))
        
        try:
            # Batch API handles grouping internally
            decisions_map = await self.triage_service.batch_assess_risk_async(code_files)
            
            # Convert to dict format expected by context
            for path, decision in decisions_map.items():
                decisions[str(path)] = decision.model_dump()
                
            # Handle any files that might have been missed (should be rare with fallback)
            for file in code_files:
                if str(file.path) not in decisions:
                    logger.warning("triage_missed_file", file=file.path)
                    fallback = TriageDecision(
                        file_path=str(file.path),
                        lane=TriageLane.MIDDLE,
                        risk_score=RiskScore(score=5, confidence=0, reasoning="Missed in batch", category="error"),
                        processing_time_ms=0
                    )
                    decisions[str(file.path)] = fallback.model_dump()

        except Exception as e:
            logger.error("triage_phase_batch_failed", error=str(e))
            # Critical fallback for phase failure
            for file in code_files:
                 fallback = TriageDecision(
                        file_path=str(file.path),
                        lane=TriageLane.MIDDLE,
                        risk_score=RiskScore(score=5, confidence=0, reasoning=f"Phase Error: {str(e)}", category="error"),
                        processing_time_ms=0
                    )
                 decisions[str(file.path)] = fallback.model_dump()

        
        # Update pipeline context
        pipeline_context.triage_decisions = decisions
        
        # Stats
        fast_count = sum(1 for d in decisions.values() if d['lane'] == TriageLane.FAST)
        middle_count = sum(1 for d in decisions.values() if d['lane'] == TriageLane.MIDDLE)
        deep_count = sum(1 for d in decisions.values() if d['lane'] == TriageLane.DEEP)
        
        duration = time.perf_counter() - start_time
        
        logger.info(
            "triage_phase_completed",
            duration=duration,
            fast=fast_count,
            middle=middle_count,
            deep=deep_count
        )
        
        if self.progress_callback:
            self.progress_callback("triage_completed", {
                "duration": f"{duration:.2f}s",
                "stats": {"fast": fast_count, "middle": middle_count, "deep": deep_count}
            })
            
        return decisions
