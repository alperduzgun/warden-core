"""Config error healer — backup corrupt config and reset to defaults."""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from warden.self_healing.models import DiagnosticResult, ErrorCategory
from warden.self_healing.registry import HealerRegistry
from warden.self_healing.strategies.base import IHealerStrategy
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)

DEFAULT_CONFIG = """\
# Warden configuration (auto-repaired)
provider: ollama
fast_model: "qwen2.5-coder:3b"
smart_model: "qwen2.5-coder:7b"
level: standard
"""


class ConfigHealer(IHealerStrategy):
    """Heals config errors by backing up corrupt YAML and resetting defaults."""

    def __init__(self, project_root: Path | None = None) -> None:
        self._project_root = project_root

    @property
    def name(self) -> str:
        return "config_healer"

    @property
    def handles(self) -> list[ErrorCategory]:
        return [ErrorCategory.CONFIG_ERROR]

    @property
    def priority(self) -> int:
        return 150

    async def can_heal(self, error: Exception, category: ErrorCategory) -> bool:
        error_msg = str(error).lower()
        return any(p in error_msg for p in ("yaml", "config", "invalid value", "missing key", "keyerror"))

    async def heal(self, error: Exception, context: str = "") -> DiagnosticResult:
        root = self._project_root or Path.cwd()
        config_path = root / ".warden" / "config.yaml"

        if not config_path.exists():
            return DiagnosticResult(
                diagnosis="Config file not found, cannot repair.",
                suggested_action="Run 'warden init' to create a new config.",
                error_category=ErrorCategory.CONFIG_ERROR,
                strategy_used=self.name,
            )

        # Backup the corrupt config
        backup_name = f"config.yaml.bak.{int(time.time())}"
        backup_path = config_path.parent / backup_name

        try:
            shutil.copy2(config_path, backup_path)
            logger.info("config_backed_up", backup=str(backup_path))
        except Exception as e:
            logger.error("config_backup_failed", error=str(e))
            return DiagnosticResult(
                diagnosis=f"Failed to backup config: {e}",
                error_category=ErrorCategory.CONFIG_ERROR,
                strategy_used=self.name,
            )

        # Write default config
        try:
            config_path.write_text(DEFAULT_CONFIG, encoding="utf-8")
            logger.info("config_reset_to_defaults", path=str(config_path))

            return DiagnosticResult(
                fixed=True,
                diagnosis=f"Corrupt config backed up to {backup_name} and reset to defaults.",
                config_repaired=True,
                should_retry=True,
                error_category=ErrorCategory.CONFIG_ERROR,
                strategy_used=self.name,
            )
        except Exception as e:
            logger.error("config_reset_failed", error=str(e))
            return DiagnosticResult(
                diagnosis=f"Failed to reset config: {e}",
                suggested_action="Manually fix .warden/config.yaml or run 'warden init'.",
                error_category=ErrorCategory.CONFIG_ERROR,
                strategy_used=self.name,
            )


HealerRegistry.register(ConfigHealer())
