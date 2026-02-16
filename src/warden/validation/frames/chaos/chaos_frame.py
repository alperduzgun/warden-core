"""
Chaos Engineering Frame - Systematic Error Injection Testing

Injects random failures to test system resilience:
- Timeouts (simulated hangs)
- Exceptions (runtime errors)
- Malformed outputs (type violations)
- Resource exhaustion
- Partial failures

Usage:
    warden scan src/ --frames chaos --level standard
"""

import asyncio
import random

from warden.shared.infrastructure.logging import get_logger
from warden.validation.domain.enums import (
    FrameApplicability,
    FrameCategory,
    FramePriority,
    FrameScope,
)
from warden.validation.domain.frame import (
    CodeFile,
    FrameResult,
    ValidationFrame,
)

logger = get_logger(__name__)


class ChaosFrame(ValidationFrame):
    """
    Chaos Engineering Frame for Resilience Testing

    Randomly injects failures to verify:
    - Error isolation (core survives)
    - Graceful degradation (partial results)
    - Logging completeness (all failures logged)
    """

    name = "Chaos Engineering Frame"
    description = "Injects random failures to test system resilience"
    category = FrameCategory.GLOBAL
    priority = FramePriority.LOW
    scope = FrameScope.FILE_LEVEL
    applicability = [FrameApplicability.ALL]

    # Chaos configuration
    FAILURE_RATE = 0.3  # 30% of files will experience chaos
    CHAOS_TYPES = ["timeout", "exception", "malformed_output", "partial_failure", "resource_exhaustion"]

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.failure_rate = config.get("failure_rate", self.FAILURE_RATE) if config else self.FAILURE_RATE
        self.chaos_seed = config.get("seed", None) if config else None
        if self.chaos_seed:
            random.seed(self.chaos_seed)  # Deterministic chaos for testing

    async def execute_async(self, code_file: CodeFile) -> FrameResult:
        """
        Execute chaos injection with configurable failure rate.

        Returns:
            - Normal FrameResult if no chaos injected
            - Raises exception or returns malformed data if chaos injected
        """
        # Decide if this file gets chaos
        if random.random() > self.failure_rate:
            # No chaos - return clean result
            logger.debug("chaos_skipped", file=code_file.path, reason="random_selection")
            return FrameResult(
                frame_id=self.id,
                frame_name=self.name,
                findings=[],
                status="passed",
                message="No chaos injected (lucky!)",
            )

        # Select chaos type
        chaos_type = random.choice(self.CHAOS_TYPES)
        logger.warning("chaos_injected", file=code_file.path, chaos_type=chaos_type)

        if chaos_type == "timeout":
            await self._inject_timeout()
        elif chaos_type == "exception":
            self._inject_exception()
        elif chaos_type == "malformed_output":
            return self._inject_malformed_output()
        elif chaos_type == "partial_failure":
            return self._inject_partial_failure(code_file)
        elif chaos_type == "resource_exhaustion":
            self._inject_resource_exhaustion()

        # Should never reach here
        return FrameResult(
            frame_id=self.id,
            frame_name=self.name,
            findings=[],
            status="failed",
            message="Chaos injection failed to trigger",
        )

    async def _inject_timeout(self):
        """Simulate infinite hang (timeout scenario)"""
        logger.error("chaos_timeout_injected", message="Simulating infinite hang")
        await asyncio.sleep(999)  # Will be killed by frame timeout

    def _inject_exception(self):
        """Raise random exception"""
        exceptions = [
            RuntimeError("Chaos: Simulated runtime error"),
            ValueError("Chaos: Invalid value encountered"),
            KeyError("Chaos: Missing required key"),
            AttributeError("Chaos: Attribute not found"),
            TypeError("Chaos: Type mismatch"),
        ]
        exception = random.choice(exceptions)
        logger.error("chaos_exception_injected", exception_type=type(exception).__name__)
        raise exception

    def _inject_malformed_output(self):
        """Return malformed FrameResult (type violation)"""
        logger.error("chaos_malformed_output_injected", message="Returning invalid type")
        # Return wrong type - should be caught by type validation
        return "This is not a FrameResult object!"  # type: ignore

    def _inject_partial_failure(self, code_file: CodeFile) -> FrameResult:
        """Return partial result with error flag"""
        logger.warning("chaos_partial_failure_injected", file=code_file.path)
        return FrameResult(
            frame_id=self.id,
            frame_name=self.name,
            findings=[],
            status="failed",
            message="Chaos: Partial failure - some checks could not complete",
            error="Simulated partial failure for resilience testing",
        )

    def _inject_resource_exhaustion(self):
        """Simulate memory exhaustion"""
        logger.error("chaos_resource_exhaustion_injected", message="Allocating large memory")
        # Allocate large list (will be caught by memory limits)
        _ = [0] * (10**8)  # 100M integers (~800MB)
        raise MemoryError("Chaos: Simulated memory exhaustion")
