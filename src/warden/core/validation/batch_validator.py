"""
Batch Processing Module - Batch Validator.

This module handles parallel validation of multiple issues with metrics tracking.
Uses asyncio for concurrent processing to improve performance.
"""

import asyncio
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

from warden.issues.domain.models import WardenIssue
from warden.core.validation.issue_validator import IssueValidator, ValidationResult


@dataclass
class BatchValidationMetrics:
    """
    Metrics from batch validation.

    Tracks rejection rate, confidence degradation, and processing stats.
    """

    total_issues: int
    valid_issues: int
    rejected_issues: int
    rejection_rate: float  # percentage (0-100)
    average_original_confidence: float
    average_adjusted_confidence: float
    average_confidence_degradation: float  # difference between original and adjusted
    processing_time_ms: float
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> Dict[str, Any]:
        """Convert to Panel-compatible JSON (camelCase)."""
        return {
            "totalIssues": self.total_issues,
            "validIssues": self.valid_issues,
            "rejectedIssues": self.rejected_issues,
            "rejectionRate": self.rejection_rate,
            "averageOriginalConfidence": self.average_original_confidence,
            "averageAdjustedConfidence": self.average_adjusted_confidence,
            "averageConfidenceDegradation": self.average_confidence_degradation,
            "processingTimeMs": self.processing_time_ms,
            "metadata": self.metadata,
        }


@dataclass
class BatchValidationResult:
    """
    Result of batch validation.

    Contains individual validation results and aggregated metrics.
    """

    results: List[ValidationResult]
    metrics: BatchValidationMetrics
    valid_issues: List[WardenIssue]
    rejected_issues: List[WardenIssue]

    def to_json(self) -> Dict[str, Any]:
        """Convert to Panel-compatible JSON (camelCase)."""
        return {
            "results": [result.to_json() for result in self.results],
            "metrics": self.metrics.to_json(),
            "validIssues": [issue.to_json() for issue in self.valid_issues],
            "rejectedIssues": [issue.to_json() for issue in self.rejected_issues],
        }


class BatchValidator:
    """
    Validates multiple issues in parallel with metrics tracking.

    Uses asyncio.gather for concurrent validation to improve performance.
    Tracks rejection rate and confidence degradation metrics.
    """

    def __init__(
        self,
        validator: Optional[IssueValidator] = None,
        max_concurrency: int = 10,
    ):
        """
        Initialize batch validator.

        Args:
            validator: Issue validator instance (creates default if None)
            max_concurrency: Maximum number of concurrent validations
        """
        self.validator = validator or IssueValidator()
        self.max_concurrency = max_concurrency

    async def validate_batch(
        self,
        issues: List[WardenIssue],
        contexts: Optional[List[Dict[str, Any]]] = None,
    ) -> BatchValidationResult:
        """
        Validate multiple issues in parallel.

        Args:
            issues: List of issues to validate
            contexts: Optional list of validation contexts (one per issue)

        Returns:
            BatchValidationResult with all results and metrics
        """
        import time

        start_time = time.perf_counter()

        # Prepare contexts (create empty dict if not provided)
        if contexts is None:
            contexts = [{} for _ in issues]
        elif len(contexts) != len(issues):
            raise ValueError(
                f"Contexts length ({len(contexts)}) must match issues length ({len(issues)})"
            )

        # Create validation tasks
        tasks = [
            self._validate_single_async(issue, context)
            for issue, context in zip(issues, contexts)
        ]

        # Execute validations in parallel with concurrency limit
        results = await self._execute_with_concurrency_limit(tasks)

        # Calculate processing time
        end_time = time.perf_counter()
        processing_time_ms = (end_time - start_time) * 1000

        # Separate valid and rejected issues
        valid_issues: List[WardenIssue] = []
        rejected_issues: List[WardenIssue] = []

        for issue, result in zip(issues, results):
            if result.is_valid:
                valid_issues.append(issue)
            else:
                rejected_issues.append(issue)

        # Calculate metrics
        metrics = self._calculate_metrics(results, processing_time_ms)

        return BatchValidationResult(
            results=results,
            metrics=metrics,
            valid_issues=valid_issues,
            rejected_issues=rejected_issues,
        )

    async def _validate_single_async(
        self,
        issue: WardenIssue,
        context: Dict[str, Any],
    ) -> ValidationResult:
        """
        Validate a single issue asynchronously.

        Wraps synchronous validator in async context.

        Args:
            issue: Issue to validate
            context: Validation context (reserved for future use)

        Returns:
            ValidationResult
        """
        # Run synchronous validation in async context
        # (IssueValidator.validate is synchronous, but we wrap it for parallel execution)
        # Note: context parameter is reserved for future use (e.g., file content)
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, self.validator.validate, issue)
        return result

    async def _execute_with_concurrency_limit(
        self,
        tasks: List[asyncio.Task],  # type: ignore
    ) -> List[ValidationResult]:
        """
        Execute tasks with concurrency limit.

        Args:
            tasks: List of async tasks

        Returns:
            List of results in original order
        """
        # Use semaphore to limit concurrency
        semaphore = asyncio.Semaphore(self.max_concurrency)

        async def bounded_task(task):  # type: ignore
            async with semaphore:
                return await task

        # Execute all tasks with concurrency limit
        bounded_tasks = [bounded_task(task) for task in tasks]
        results = await asyncio.gather(*bounded_tasks)

        return results

    def _calculate_metrics(
        self,
        results: List[ValidationResult],
        processing_time_ms: float,
    ) -> BatchValidationMetrics:
        """
        Calculate batch validation metrics.

        Args:
            results: List of validation results
            processing_time_ms: Total processing time in milliseconds

        Returns:
            BatchValidationMetrics with aggregated statistics
        """
        total_issues = len(results)

        if total_issues == 0:
            return BatchValidationMetrics(
                total_issues=0,
                valid_issues=0,
                rejected_issues=0,
                rejection_rate=0.0,
                average_original_confidence=0.0,
                average_adjusted_confidence=0.0,
                average_confidence_degradation=0.0,
                processing_time_ms=processing_time_ms,
            )

        # Count valid and rejected
        valid_count = sum(1 for r in results if r.is_valid)
        rejected_count = total_issues - valid_count

        # Calculate averages
        total_original = sum(r.original_confidence for r in results)
        total_adjusted = sum(r.adjusted_confidence for r in results)

        avg_original = total_original / total_issues
        avg_adjusted = total_adjusted / total_issues
        avg_degradation = avg_original - avg_adjusted

        # Calculate rejection rate (percentage)
        rejection_rate = (rejected_count / total_issues) * 100

        return BatchValidationMetrics(
            total_issues=total_issues,
            valid_issues=valid_count,
            rejected_issues=rejected_count,
            rejection_rate=rejection_rate,
            average_original_confidence=avg_original,
            average_adjusted_confidence=avg_adjusted,
            average_confidence_degradation=avg_degradation,
            processing_time_ms=processing_time_ms,
        )
