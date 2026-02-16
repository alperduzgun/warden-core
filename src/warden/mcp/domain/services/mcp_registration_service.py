import contextlib
import json
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from warden.mcp.infrastructure.mcp_config_paths import get_mcp_config_paths, is_safe_to_create_dir

logger = logging.getLogger(__name__)


@dataclass
class RegistrationResult:
    tool_name: str
    status: str  # "registered", "skipped", "error"
    config_path: Path
    message: str | None = None


class MCPRegistrationService:
    """
    Domain service for registering Warden MCP with AI tools.
    Decouples business logic from CLI presentation.
    """

    def __init__(self, warden_path: str):
        self.warden_path = warden_path

    def register_all(self) -> dict[str, RegistrationResult]:
        """
        Register with all known AI tools.

        Returns:
            Dict mapping tool name to RegistrationResult
        """
        config_locations = get_mcp_config_paths()
        results = {}

        # Consistent config for all tools
        mcp_config = {
            "command": self.warden_path,
            "args": ["serve", "mcp", "start"],
        }

        for tool_name, config_path in config_locations.items():
            results[tool_name] = self._register_single_tool(tool_name, config_path, mcp_config)

        return results

    def _register_single_tool(
        self, tool_name: str, config_path: Path, mcp_config: dict[str, Any]
    ) -> RegistrationResult:
        """Register for a single tool with safety checks."""

        # 1. Directory Creation (with security check)
        if not config_path.parent.exists():
            if is_safe_to_create_dir(config_path.parent):
                try:
                    config_path.parent.mkdir(parents=True, exist_ok=True)
                except OSError as e:
                    return RegistrationResult(tool_name, "error", config_path, f"Cannot create directory: {e}")
            else:
                return RegistrationResult(tool_name, "skipped", config_path, "Unsafe directory creation prevented")

        try:
            # 2. Read existing (Self-Healing)
            data = self._read_config_safe(config_path)

            # Ensure structure
            if "mcpServers" not in data or not isinstance(data.get("mcpServers"), dict):
                data["mcpServers"] = {}

            # 3. Idempotency Check
            existing = data["mcpServers"].get("warden")
            if isinstance(existing, dict) and existing.get("command") == self.warden_path:
                return RegistrationResult(tool_name, "skipped", config_path, "Already registered")

            # 4. Update Config
            data["mcpServers"]["warden"] = mcp_config

            # 5. Atomic Write
            self._write_config_atomic(config_path, data)

            return RegistrationResult(tool_name, "registered", config_path)

        except Exception as e:
            return RegistrationResult(tool_name, "error", config_path, str(e))

    def _read_config_safe(self, path: Path) -> dict[str, Any]:
        """Read JSON with backup on corruption."""
        if not path.exists():
            return {}

        try:
            with open(path, encoding="utf-8") as f:
                content = f.read().strip()
                return json.loads(content) if content else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            # Self-healing: Backup corrupt file implies we start fresh
            backup = path.parent / f"{path.stem}.corrupt.json"
            with contextlib.suppress(OSError):
                shutil.copy2(path, backup)
            return {}

    def _write_config_atomic(self, path: Path, data: dict[str, Any]) -> None:
        """Atomic write pattern."""
        fd, temp_path = tempfile.mkstemp(dir=path.parent, prefix=".mcp_reg_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(temp_path, path)
        except Exception:
            with contextlib.suppress(OSError):
                os.unlink(temp_path)
            raise
