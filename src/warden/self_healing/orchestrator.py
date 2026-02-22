"""Self-healing orchestrator — coordinates classification, strategies, cache, and metrics."""

from __future__ import annotations

from pathlib import Path

# Ensure all strategies are registered on import
import warden.self_healing.strategies.config_healer
import warden.self_healing.strategies.import_healer
import warden.self_healing.strategies.llm_healer
import warden.self_healing.strategies.model_healer
import warden.self_healing.strategies.provider_healer
from warden.self_healing.cache import HealingCache
from warden.self_healing.classifier import ErrorClassifier
from warden.self_healing.metrics import HealingMetrics, HealingMetricsCollector
from warden.self_healing.models import DiagnosticResult, ErrorCategory, HealingRecord
from warden.self_healing.registry import HealerRegistry
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)

MAX_HEAL_ATTEMPTS = 2

# Per-session attempt counters (prevents infinite loops)
_heal_attempts: dict[str, int] = {}


class SelfHealingOrchestrator:
    """Coordinates error classification, strategy selection, caching and metrics.

    Flow:
    1. Check attempt limit (max 2 per error key)
    2. Cache lookup (replay known fix or skip known failure)
    3. Classify error -> ErrorCategory
    4. Registry -> matching strategies (priority order)
    5. First successful strategy -> return result
    6. Cache + Metrics record
    7. Return DiagnosticResult
    """

    def __init__(
        self,
        max_attempts: int = MAX_HEAL_ATTEMPTS,
        project_root: Path | None = None,
    ) -> None:
        self._max_attempts = max_attempts
        self._project_root = project_root or Path.cwd()
        self._classifier = ErrorClassifier()
        self._cache = HealingCache(self._project_root)
        self._metrics = HealingMetricsCollector()

        # Re-register ConfigHealer with project_root so it doesn't use cwd()
        from warden.self_healing.strategies.config_healer import ConfigHealer

        HealerRegistry.register(ConfigHealer(project_root=self._project_root))

    async def diagnose_and_fix(
        self,
        error: Exception,
        context: str = "",
    ) -> DiagnosticResult:
        """Diagnose and attempt to fix a runtime error."""
        error_key = HealingRecord.make_error_key(error)

        # 1. Attempt limit
        attempt_count = _heal_attempts.get(error_key, 0)
        if attempt_count >= self._max_attempts:
            logger.warning(
                "self_healing_max_attempts_reached",
                error_key=error_key,
                attempts=attempt_count,
            )
            return DiagnosticResult(
                diagnosis=f"Max healing attempts ({self._max_attempts}) reached for this error.",
                suggested_action="Run 'warden doctor' to check your setup.",
            )

        _heal_attempts[error_key] = attempt_count + 1
        self._metrics.start_timer(error_key)

        # 2. Cache lookup
        cached = self._cache.get(error_key)
        if cached is not None:
            self._metrics.record_cache_hit()
            if cached.fixed:
                logger.info("self_healing_cache_hit", error_key=error_key, action=cached.action_taken)
                duration = self._metrics.stop_timer(error_key)
                result = DiagnosticResult(
                    fixed=True,
                    diagnosis=f"Cache hit: {cached.action_taken}",
                    should_retry=True,
                    error_category=ErrorCategory(cached.error_category),
                    strategy_used=cached.strategy_used,
                    duration_ms=duration,
                )
                self._metrics.record_attempt(ErrorCategory(cached.error_category))
                self._metrics.record_result(result)
                return result
            # Cached failure — skip that strategy but continue with others
            logger.debug("self_healing_cache_skip", error_key=error_key, strategy=cached.strategy_used)
        else:
            self._metrics.record_cache_miss()

        # 3. Classify
        category = self._classifier.classify(error)
        self._metrics.record_attempt(category)
        logger.info(
            "self_healing_started",
            error_type=type(error).__name__,
            category=category.value,
            attempt=attempt_count + 1,
        )

        # 4. Get matching strategies
        strategies = HealerRegistry.get_for_category(category)

        # Filter out cached failures
        if cached and not cached.fixed:
            strategies = [s for s in strategies if s.name != cached.strategy_used]

        # 5. Try each strategy — first successful fix wins
        last_result = None
        for strategy in strategies:
            try:
                if not await strategy.can_heal(error, category):
                    continue

                result = await strategy.heal(error, context)
                result.error_category = category

                if result.fixed:
                    duration = self._metrics.stop_timer(error_key)
                    result.duration_ms = duration
                    self._record(error_key, category, strategy.name, result)
                    return result

                # Not fixed — remember last result, try next strategy
                last_result = result

            except (OSError, ValueError, RuntimeError, TypeError) as e:
                logger.debug(
                    "strategy_failed",
                    strategy=strategy.name,
                    error_key=error_key,
                    category=category.value,
                    error=str(e),
                )
                continue

        # Categories where a dedicated strategy already provided diagnostic — don't fallback to LLM
        _diagnostic_only_categories = {
            ErrorCategory.TIMEOUT,
            ErrorCategory.EXTERNAL_SERVICE,
            ErrorCategory.PERMISSION_ERROR,
            ErrorCategory.PROVIDER_UNAVAILABLE,
        }

        # If we have a last_result from a diagnostic-only category, return it
        if last_result is not None and category in _diagnostic_only_categories:
            duration = self._metrics.stop_timer(error_key)
            last_result.duration_ms = duration
            strategy_name = last_result.strategy_used or "none"
            self._record(error_key, category, strategy_name, last_result)
            return last_result

        # Try LLM fallback for fixable categories where initial strategy failed
        if category != ErrorCategory.UNKNOWN:
            llm_strategy = HealerRegistry.get("llm_healer")
            if llm_strategy and (not cached or cached.strategy_used != "llm_healer"):
                try:
                    result = await llm_strategy.heal(error, context)
                    duration = self._metrics.stop_timer(error_key)
                    result.duration_ms = duration
                    result.error_category = category
                    self._record(error_key, category, "llm_healer", result)
                    return result
                except (OSError, ValueError, RuntimeError, TypeError) as e:
                    logger.debug(
                        "llm_fallback_failed",
                        error_key=error_key,
                        error=str(e),
                    )

        # Nothing worked —
        duration = self._metrics.stop_timer(error_key)
        if last_result is not None:
            last_result.duration_ms = duration
            strategy_name = last_result.strategy_used or "none"
            self._record(error_key, category, strategy_name, last_result)
            return last_result

        result = DiagnosticResult(
            diagnosis=f"Unhandled {type(error).__name__}: {error}",
            suggested_action="Run 'warden doctor' to check your setup, or report this issue.",
            error_category=category,
            duration_ms=duration,
        )
        self._record(error_key, category, "none", result)
        return result

    def _record(
        self,
        error_key: str,
        category: ErrorCategory,
        strategy_name: str,
        result: DiagnosticResult,
    ) -> None:
        """Record result to cache and metrics."""
        self._metrics.record_result(result)

        action = _summarize_action(result)
        record = HealingRecord(
            error_key=error_key,
            error_category=category.value,
            strategy_used=strategy_name,
            fixed=result.fixed,
            action_taken=action,
            duration_ms=result.duration_ms,
        )
        self._cache.put(record)
        self._cache.flush()

    def get_metrics(self) -> HealingMetrics:
        return self._metrics.get_metrics()

    def reset_attempts(self) -> None:
        """Reset attempt counters. Useful for testing."""
        _heal_attempts.clear()

    @property
    def cache(self) -> HealingCache:
        return self._cache

    # ── Backward-compatible shims for old SelfHealingDiagnostic API ──────

    def _classify_error(self, error: Exception) -> ErrorCategory:
        return self._classifier.classify(error)

    @staticmethod
    def _extract_module_from_import_error(error: Exception) -> str | None:
        return ErrorClassifier.extract_module_name(error)

    @staticmethod
    def _try_pip_install(pip_name: str) -> bool:
        from warden.self_healing.strategies.import_healer import _try_pip_install

        return _try_pip_install(pip_name)

    @staticmethod
    def _parse_llm_fix(diagnosis: str) -> list[str]:
        from warden.self_healing.strategies.llm_healer import _parse_llm_fix

        return _parse_llm_fix(diagnosis)

    @staticmethod
    async def _ask_llm_diagnosis(error: Exception, traceback_str: str, context: str) -> str | None:
        from warden.self_healing.strategies.llm_healer import _ask_llm_diagnosis

        return await _ask_llm_diagnosis(error, traceback_str, context)


def _summarize_action(result: DiagnosticResult) -> str:
    """Build a short action summary for cache storage."""
    parts = []
    if result.packages_installed:
        parts.append(f"pip_install:{','.join(result.packages_installed)}")
    if result.models_pulled:
        parts.append(f"ollama_pull:{','.join(result.models_pulled)}")
    if result.config_repaired:
        parts.append("config_reset")
    if not parts:
        parts.append("diagnosis_only")
    return "|".join(parts)


def reset_heal_attempts() -> None:
    """Module-level reset for backward compatibility."""
    _heal_attempts.clear()
