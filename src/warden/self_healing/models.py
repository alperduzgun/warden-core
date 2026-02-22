"""Domain models for the self-healing module."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from enum import Enum


class ErrorCategory(Enum):
    """Classification of runtime errors."""

    IMPORT_ERROR = "import_error"
    MODULE_NOT_FOUND = "module_not_found"
    TIMEOUT = "timeout"
    CONFIG_ERROR = "config_error"
    EXTERNAL_SERVICE = "external_service"
    PERMISSION_ERROR = "permission_error"
    MODEL_NOT_FOUND = "model_not_found"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    UNKNOWN = "unknown"


@dataclass
class DiagnosticResult:
    """Result of a self-healing diagnostic attempt."""

    fixed: bool = False
    diagnosis: str = ""
    packages_installed: list[str] = field(default_factory=list)
    models_pulled: list[str] = field(default_factory=list)
    config_repaired: bool = False
    should_retry: bool = False
    suggested_action: str | None = None
    error_category: ErrorCategory = ErrorCategory.UNKNOWN
    strategy_used: str | None = None
    duration_ms: int = 0


@dataclass
class HealingRecord:
    """Persistent record of a healing attempt for cache storage."""

    error_key: str
    error_category: str
    strategy_used: str
    fixed: bool
    action_taken: str
    timestamp: float = field(default_factory=time.time)
    duration_ms: int = 0

    @staticmethod
    def make_error_key(error: Exception) -> str:
        """Generate a stable key from error type + message.

        Includes the exception type name in the hash so that different
        exception types with identical (or empty) messages produce
        distinct keys.
        """
        msg = str(error)[:200]
        raw = f"{type(error).__qualname__}:{msg}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        return {
            "error_key": self.error_key,
            "error_category": self.error_category,
            "strategy_used": self.strategy_used,
            "fixed": self.fixed,
            "action_taken": self.action_taken,
            "timestamp": self.timestamp,
            "duration_ms": self.duration_ms,
        }

    @classmethod
    def from_dict(cls, data: dict) -> HealingRecord:
        """Deserialize from dict with explicit type coercion.

        Raises ``ValueError`` on missing required keys so the caller
        can evict the corrupt entry.
        """
        required = ("error_key", "error_category", "strategy_used", "fixed", "action_taken")
        for key in required:
            if key not in data:
                raise ValueError(f"HealingRecord missing required key: {key}")

        # Explicit coercion guards against e.g. "false" → bool("false") == True
        fixed_raw = data["fixed"]
        if isinstance(fixed_raw, str):
            fixed = fixed_raw.lower() in ("true", "1", "yes")
        else:
            fixed = bool(fixed_raw)

        return cls(
            error_key=str(data["error_key"]),
            error_category=str(data["error_category"]),
            strategy_used=str(data["strategy_used"]),
            fixed=fixed,
            action_taken=str(data["action_taken"]),
            timestamp=float(data.get("timestamp", 0.0)),
            duration_ms=int(data.get("duration_ms", 0)),
        )
