"""
Health Adapter

MCP adapter for health and status tools.
Maps to gRPC HealthStatusMixin functionality.
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from warden.mcp.infrastructure.adapters.base_adapter import BaseWardenAdapter
from warden.mcp.domain.models import MCPToolDefinition, MCPToolResult
from warden.mcp.domain.enums import ToolCategory


class HealthAdapter(BaseWardenAdapter):
    """
    Adapter for health and status tools.

    Tools:
        - warden_health_check: Basic health check
        - warden_get_server_status: Detailed server status
        - warden_setup_status: Check setup completeness for AI tools
    """

    SUPPORTED_TOOLS = frozenset({
        "warden_health_check",
        "warden_get_server_status",
        "warden_setup_status",
    })
    TOOL_CATEGORY = ToolCategory.STATUS

    def __init__(self, project_root: Path, bridge: Any = None) -> None:
        """Initialize health adapter with start time tracking."""
        super().__init__(project_root, bridge)
        self._start_time = datetime.now()

    def get_tool_definitions(self) -> List[MCPToolDefinition]:
        """Get health tool definitions."""
        return [
            self._create_tool_definition(
                name="warden_health_check",
                description="Check if Warden service is healthy and responsive",
                properties={},
            ),
            self._create_tool_definition(
                name="warden_get_server_status",
                description="Get detailed server status including uptime, memory, and component status",
                properties={},
            ),
            self._create_tool_definition(
                name="warden_setup_status",
                description="Check Warden setup completeness. Use this FIRST to detect if project needs initialization or configuration. Returns missing steps that AI should help user complete.",
                properties={},
            ),
        ]

    async def _execute_tool_async(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> MCPToolResult:
        """Execute health tool."""
        if tool_name == "warden_health_check":
            return await self._health_check_async()
        elif tool_name == "warden_get_server_status":
            return await self._get_server_status_async()
        elif tool_name == "warden_setup_status":
            return await self._get_setup_status_async()
        else:
            return MCPToolResult.error(f"Unknown tool: {tool_name}")

    async def _health_check_async(self) -> MCPToolResult:
        """Perform health check."""
        uptime = (datetime.now() - self._start_time).total_seconds()

        # Check component availability
        components = {
            "bridge": self.bridge is not None,
            "project_root": self.project_root.exists(),
        }

        # Check if bridge has orchestrator
        if self.bridge:
            components["orchestrator"] = getattr(self.bridge, "orchestrator", None) is not None
            components["llm"] = getattr(self.bridge, "llm_config", None) is not None

        all_healthy = all(components.values())

        return MCPToolResult.json_result({
            "healthy": all_healthy,
            "status": "ok" if all_healthy else "degraded",
            "version": self._get_version(),
            "uptime_seconds": round(uptime, 2),
            "components": components,
            "timestamp": datetime.utcnow().isoformat(),
        })

    async def _get_server_status_async(self) -> MCPToolResult:
        """Get detailed server status."""
        import sys

        uptime = (datetime.now() - self._start_time).total_seconds()

        # Get memory usage if available
        memory_mb = None
        try:
            import resource
            rusage = resource.getrusage(resource.RUSAGE_SELF)
            memory_mb = rusage.ru_maxrss / 1024  # Convert to MB on macOS
            if sys.platform == "linux":
                memory_mb = rusage.ru_maxrss / 1024  # Already in KB on Linux
        except Exception:
            pass

        # Get Python info
        python_info = {
            "version": sys.version,
            "platform": sys.platform,
            "executable": sys.executable,
        }

        # Get project info
        project_info = {
            "root": str(self.project_root),
            "exists": self.project_root.exists(),
            "warden_dir": (self.project_root / ".warden").exists(),
        }

        # Get bridge status
        bridge_status = {
            "available": self.bridge is not None,
            "orchestrator": False,
            "llm": False,
            "config_name": None,
        }

        if self.bridge:
            bridge_status["orchestrator"] = getattr(self.bridge, "orchestrator", None) is not None
            bridge_status["llm"] = getattr(self.bridge, "llm_config", None) is not None
            bridge_status["config_name"] = getattr(self.bridge, "active_config_name", None)

        return MCPToolResult.json_result({
            "running": True,
            "uptime_seconds": round(uptime, 2),
            "memory_mb": memory_mb,
            "python": python_info,
            "project": project_info,
            "bridge": bridge_status,
            "version": self._get_version(),
            "timestamp": datetime.utcnow().isoformat(),
        })

    def _get_version(self) -> str:
        """Get Warden version."""
        try:
            from warden._version import __version__
            return __version__
        except ImportError:
            return "unknown"

    async def _get_setup_status_async(self) -> MCPToolResult:
        """
        Check Warden setup completeness for AI assistant integration.

        Returns detailed status about what's configured and what's missing,
        allowing AI assistants to guide users through setup completion.
        """
        import json

        setup_status = {
            "warden_installed": True,  # If this runs, Warden is installed
            "project_initialized": False,
            "llm_configured": False,
            "ai_tools_configured": False,
            "baseline_exists": False,
            "ready_for_use": False,
            "missing_steps": [],
            "next_action": None,
            "setup_commands": [],
        }

        warden_dir = self.project_root / ".warden"

        # Check 1: Project initialized (.warden directory exists)
        if warden_dir.exists():
            setup_status["project_initialized"] = True
        else:
            setup_status["missing_steps"].append({
                "step": "project_init",
                "description": "Project not initialized with Warden",
                "command": "warden init",
                "priority": 1,
            })
            setup_status["setup_commands"].append("warden init")

        # Check 2: Config exists and has LLM provider
        config_path = warden_dir / "config.yaml"
        if config_path.exists():
            try:
                import yaml
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f) or {}

                llm_config = config.get("llm", {})
                provider = llm_config.get("provider")

                if provider and provider != "none":
                    setup_status["llm_configured"] = True
                else:
                    setup_status["missing_steps"].append({
                        "step": "llm_config",
                        "description": "LLM provider not configured (needed for AI-powered analysis)",
                        "command": "warden init --reconfigure",
                        "priority": 2,
                    })
            except Exception:
                pass

        # Check 3: AI tool files exist (CLAUDE.md, .cursorrules)
        ai_files_status = {
            "CLAUDE.md": (self.project_root / "CLAUDE.md").exists(),
            ".cursorrules": (self.project_root / ".cursorrules").exists(),
            "AI_RULES.md": (warden_dir / "AI_RULES.md").exists(),
            "ai_status.md": (warden_dir / "ai_status.md").exists(),
        }

        if all(ai_files_status.values()):
            setup_status["ai_tools_configured"] = True
        else:
            missing_files = [k for k, v in ai_files_status.items() if not v]
            setup_status["missing_steps"].append({
                "step": "ai_tool_files",
                "description": f"AI integration files missing: {', '.join(missing_files)}",
                "command": "warden init",
                "priority": 2,
            })

        # Check 4: Baseline exists
        baseline_dir = warden_dir / "baseline"
        baseline_file = warden_dir / "baseline.sarif"
        if baseline_dir.exists() or baseline_file.exists():
            setup_status["baseline_exists"] = True
        else:
            setup_status["missing_steps"].append({
                "step": "baseline",
                "description": "Security baseline not created (run initial scan)",
                "command": "warden scan",
                "priority": 3,
            })
            setup_status["setup_commands"].append("warden scan")

        # Check 5: Recent scan status
        ai_status_path = warden_dir / "ai_status.md"
        if ai_status_path.exists():
            try:
                content = ai_status_path.read_text(encoding='utf-8')
                if "PASS" in content:
                    setup_status["last_scan_status"] = "PASS"
                elif "FAIL" in content:
                    setup_status["last_scan_status"] = "FAIL"
                    setup_status["missing_steps"].append({
                        "step": "fix_issues",
                        "description": "Last scan found issues - check .warden/reports/",
                        "command": "warden scan",
                        "priority": 1,
                    })
                else:
                    setup_status["last_scan_status"] = "PENDING"
            except Exception:
                setup_status["last_scan_status"] = "UNKNOWN"

        # Determine overall readiness
        setup_status["ready_for_use"] = (
            setup_status["project_initialized"] and
            setup_status["ai_tools_configured"] and
            setup_status["baseline_exists"]
        )

        # Set next action based on priority
        if setup_status["missing_steps"]:
            sorted_steps = sorted(setup_status["missing_steps"], key=lambda x: x["priority"])
            setup_status["next_action"] = sorted_steps[0]
        else:
            setup_status["next_action"] = {
                "step": "ready",
                "description": "Warden is fully configured and ready to use",
                "command": "warden scan",
            }

        # AI guidance message
        if not setup_status["ready_for_use"]:
            setup_status["ai_guidance"] = (
                "Warden setup is incomplete. Please help the user complete the missing steps. "
                f"Run: {' && '.join(setup_status['setup_commands']) or 'warden init'}"
            )
        else:
            setup_status["ai_guidance"] = (
                "Warden is ready. Follow the protocol in CLAUDE.md: "
                "read .warden/ai_status.md before coding, run 'warden scan' after changes."
            )

        return MCPToolResult.json_result(setup_status)
