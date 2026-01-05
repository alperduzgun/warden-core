"""
Fortification Phase Executor.
"""

import time
import traceback
from typing import List

from warden.pipeline.domain.pipeline_context import PipelineContext
from warden.validation.domain.frame import CodeFile
from warden.shared.infrastructure.logging import get_logger
from warden.pipeline.application.executors.base_phase_executor import BasePhaseExecutor

logger = get_logger(__name__)


class FortificationExecutor(BasePhaseExecutor):
    """Executor for the FORTIFICATION phase."""

    async def execute_async(
        self,
        context: PipelineContext,
        code_files: List[CodeFile],
    ) -> None:
        """Execute FORTIFICATION phase."""
        logger.info("executing_phase", phase="FORTIFICATION")

        if self.progress_callback:
            start_time = time.perf_counter()
            self.progress_callback("phase_started", {
                "phase": "FORTIFICATION",
                "phase_name": "FORTIFICATION"
            })

        try:
            from warden.fortification.application.fortification_phase import FortificationPhase

            # Get context from previous phases
            phase_context = context.get_context_for_phase("FORTIFICATION")

            phase = FortificationPhase(
                config=getattr(self.config, 'fortification_config', {}),
                context=phase_context,
                llm_service=self.llm_service,
                semantic_search_service=self.semantic_search_service,
            )

            # Ensure validated_issues exists and is a list
            validated_issues = getattr(context, 'validated_issues', [])
            if validated_issues is None:
                validated_issues = []

            result = await phase.execute_async(validated_issues)

            # Store results in context
            context.fortifications = result.fortifications
            context.applied_fixes = result.applied_fixes
            context.security_improvements = result.security_improvements

            # Add phase result
            context.add_phase_result("FORTIFICATION", {
                "fortifications_count": len(result.fortifications),
                "critical_fixes": len([f for f in result.fortifications if f.get("severity") == "critical"]),
                "auto_fixable": len([f for f in result.fortifications if f.get("auto_fixable")]),
            })

            logger.info(
                "phase_completed",
                phase="FORTIFICATION",
                fortifications=len(result.fortifications),
            )

        except Exception as e:
            logger.error("phase_failed",
                        phase="FORTIFICATION",
                        error=str(e),
                        error_type=type(e).__name__,
                        traceback=traceback.format_exc())
            context.errors.append(f"FORTIFICATION failed: {str(e)}")

        if self.progress_callback:
            duration = time.perf_counter() - start_time
            fortification_data = {
                "phase": "FORTIFICATION",
                "phase_name": "FORTIFICATION",
                "duration": duration
            }
            # Check if LLM was used in this phase
            if self.llm_service and hasattr(context, 'fortifications') and context.fortifications:
                 fortification_data["llm_used"] = True
                 fortification_data["fixes_generated"] = len(context.fortifications)
            
            self.progress_callback("phase_completed", fortification_data)
