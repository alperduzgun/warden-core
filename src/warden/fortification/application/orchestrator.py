"""
Code Fortifier - Main Orchestrator

Coordinates all fortifiers to add safety measures to code.
Executes fortifiers in priority order and combines results.
"""

import structlog
from typing import List, Optional

from warden.fortification.domain.base import BaseFortifier
from warden.fortification.domain.models import FortificationResult, FortificationAction
from warden.fortification.application.fortifiers import (
    ErrorHandlingFortifier,
    LoggingFortifier,
    InputValidationFortifier,
    ResourceDisposalFortifier,
)
from warden.validation.domain.frame import CodeFile

# AnalysisResult is optional - for future integration
try:
    from warden.analysis.application.discovery.analyzer import AnalysisResult
except ImportError:
    AnalysisResult = None  # type: ignore

logger = structlog.get_logger()


class FortificationOrchestrator:
    """
    Main code fortifier that orchestrates all fortification operations.

    Executes fortifiers in priority order:
    1. Input Validation (CRITICAL)
    2. Error Handling (HIGH)
    3. Resource Disposal (HIGH)
    4. Logging (MEDIUM)
    """

    def __init__(self, fortifiers: Optional[List[BaseFortifier]] = None):
        """
        Initialize Code Fortifier.

        Args:
            fortifiers: Optional list of fortifiers. If None, uses default set.
        """
        if fortifiers is None:
            # Default fortifiers
            self._fortifiers = [
                InputValidationFortifier(),
                ErrorHandlingFortifier(),
                ResourceDisposalFortifier(),
                LoggingFortifier(),
            ]
        else:
            self._fortifiers = fortifiers

        # Sort by priority (CRITICAL first)
        self._fortifiers.sort(key=lambda f: f.priority.value)

        logger.info(
            "code_fortifier_initialized",
            fortifier_count=len(self._fortifiers),
            fortifiers=[f.name for f in self._fortifiers],
        )

    async def fortify_async(
        self,
        code_file: CodeFile,
        analysis_result: Optional[AnalysisResult] = None,
        cancellation_token: Optional[str] = None,
    ) -> FortificationResult:
        """
        Fortify code by applying all fortifiers in sequence.

        Args:
            code_file: The code file to fortify
            analysis_result: Optional analysis results to guide fortification
            cancellation_token: Optional cancellation token

        Returns:
            Combined fortification result

        Raises:
            ValueError: If code_file is None or empty
        """
        if not code_file or not code_file.content:
            raise ValueError("Code file cannot be None or empty")

        logger.info(
            "fortification_started",
            file_path=code_file.file_path,
            fortifier_count=len(self._fortifiers),
        )

        # Start with original code
        current_code = code_file.content
        all_actions: List[FortificationAction] = []
        failed_fortifiers: List[str] = []

        # Apply each fortifier in sequence
        for fortifier in self._fortifiers:
            try:
                logger.debug(
                    "applying_fortifier",
                    fortifier=fortifier.name,
                    priority=fortifier.priority.name,
                )

                # Update code file with current state
                fortification_input = CodeFile(
                    file_path=code_file.file_path,
                    content=current_code,
                    language=code_file.language,
                )

                result = await fortifier.fortify_async(
                    fortification_input, cancellation_token
                )

                if result.success:
                    # Update current code for next fortifier
                    current_code = result.fortified_code
                    all_actions.extend(result.actions)

                    logger.info(
                        "fortifier_applied",
                        fortifier=fortifier.name,
                        actions_count=len(result.actions),
                        summary=result.summary,
                    )
                else:
                    failed_fortifiers.append(fortifier.name)
                    logger.warning(
                        "fortifier_failed",
                        fortifier=fortifier.name,
                        error=result.error_message,
                    )

            except Exception as e:
                failed_fortifiers.append(fortifier.name)
                logger.error(
                    "fortifier_exception",
                    fortifier=fortifier.name,
                    error=str(e),
                    error_type=type(e).__name__,
                )

        # Build combined result
        success = len(failed_fortifiers) == 0
        summary = self._build_summary(all_actions, failed_fortifiers)

        logger.info(
            "fortification_completed",
            success=success,
            actions_count=len(all_actions),
            failed_fortifiers=failed_fortifiers,
        )

        return FortificationResult(
            success=success,
            original_code=code_file.content,
            fortified_code=current_code,
            actions=all_actions,
            summary=summary,
            error_message=(
                f"Failed fortifiers: {', '.join(failed_fortifiers)}"
                if failed_fortifiers
                else None
            ),
            fortifier_name="FortificationOrchestrator",
        )


    @staticmethod
    def _build_summary(
        actions: List[FortificationAction], failed_fortifiers: List[str]
    ) -> str:
        """
        Build human-readable summary of fortification.

        Args:
            actions: All fortification actions applied
            failed_fortifiers: List of fortifiers that failed

        Returns:
            Summary string
        """
        if not actions and not failed_fortifiers:
            return "No fortification needed - code is already safe!"

        lines = []

        if actions:
            # Group actions by type
            action_groups = {}
            for action in actions:
                action_type = action.type.value
                if action_type not in action_groups:
                    action_groups[action_type] = 0
                action_groups[action_type] += 1

            lines.append(f"Applied {len(actions)} safety improvements:")
            for action_type, count in action_groups.items():
                lines.append(f"  - {action_type.replace('_', ' ').title()}: {count}")

        if failed_fortifiers:
            lines.append(f"\nWarning: {len(failed_fortifiers)} fortifiers failed")

        return "\n".join(lines)

    def get_fortifiers(self) -> List[BaseFortifier]:
        """Get list of registered fortifiers."""
        return self._fortifiers.copy()

    def add_fortifier(self, fortifier: BaseFortifier) -> None:
        """
        Add a new fortifier.

        Args:
            fortifier: Fortifier to add
        """
        self._fortifiers.append(fortifier)
        self._fortifiers.sort(key=lambda f: f.priority.value)

        logger.info("fortifier_added", fortifier=fortifier.name)
