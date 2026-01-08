"""
Warden Bridge - Core IPC Service

Exposes Warden's Python backend functionality to the Ink CLI through JSON-RPC.
Refactored into modular handlers to maintain < 500 lines per core rules.
"""

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional, AsyncIterator
from datetime import datetime

from warden.cli_bridge.protocol import IPCError, ErrorCode
from warden.shared.infrastructure.logging import get_logger
from warden.cli_bridge.handlers.config_handler import ConfigHandler
from warden.cli_bridge.handlers.pipeline_handler import PipelineHandler
from warden.cli_bridge.handlers.llm_handler import LLMHandler
from warden.cli_bridge.handlers.tool_handler import ToolHandler
from warden.cli_bridge.utils import serialize_pipeline_result

logger = get_logger(__name__)

class WardenBridge:
    """
    Core bridge service exposing Warden functionality via IPC.
    Delegates implementation to specialized handlers for modularity.
    """

    def __init__(self, project_root: Optional[Path] = None, config_path: Optional[str] = None) -> None:
        self.project_root = Path(project_root) if project_root else Path.cwd()
        
        # Initialize basic handlers
        self.config_handler = ConfigHandler(self.project_root)
        self.tool_handler = ToolHandler()
        
        # Load LLM Config first for orchestrator creation
        from warden.llm.config import load_llm_config
        from warden.llm.factory import create_client
        try:
            self.llm_config = load_llm_config()
            self.llm_handler = LLMHandler(self.llm_config)
            llm_service = create_client(self.llm_config.default_provider)
        except Exception as e:
            logger.warning("llm_init_failed_in_bridge", error=str(e))
            self.llm_config = None
            self.llm_handler = None
            llm_service = None

        # Load pipeline configuration and frames
        config_data = self.config_handler.load_pipeline_config(config_path)
        self.active_config_name = config_data["name"]

        # Initialize Orchestrator
        from warden.pipeline.application.phase_orchestrator import PhaseOrchestrator
        self.orchestrator = PhaseOrchestrator(
            frames=config_data["frames"],
            config=config_data["config"],
            llm_service=llm_service,
            available_frames=config_data["available_frames"]
        )
        
        self.pipeline_handler = PipelineHandler(self.orchestrator, self.project_root)
        self.config_handler.validate_consistency()
        
        # Store LLM service for semantic tools
        self.llm_service = llm_service

        logger.info("warden_bridge_initialized", config=self.active_config_name, orchestrator=self.orchestrator is not None)

    # --- Semantic Fixes ---

    async def request_fix(self, file_path: str, line_number: int, issue_type: str, context_code: str = "") -> Dict[str, Any]:
        """Request a semantic fix for a vulnerability."""
        from warden.fortification.application.fortification_phase import FortificationPhase
        
        # Create minimal context for fortification
        context = {
            "project_root": self.project_root,
            "language": self.pipeline_handler._detect_language(Path(file_path)),
            "project_type": "unknown", # Could be detected
            "framework": "unknown"     # Could be detected
        }
        
        # Initialize phase with LLM service
        phase = FortificationPhase(
            config={"use_llm": True},
            context=context,
            llm_service=self.llm_service
        )
        
        # Create minimal finding representation
        finding = {
            "type": issue_type,
            "severity": "medium", # Default
            "message": f"Fix requested for {issue_type}",
            "file_path": file_path,
            "line_number": line_number,
            "code_snippet": context_code,
            "id": "manual-request"
        }
        
        # Generate fix directly using generator logic
        # We access the internal generator for a single targeted fix
        from warden.fortification.application.llm_fortification_generator import LLMFortificationGenerator
        generator = LLMFortificationGenerator(self.llm_service)
        
        fix = await generator.generate_fortification(
            finding=finding,
            code_context=context_code,
            framework=context["framework"],
            language=context["language"]
        )
        
        if fix:
            return fix.to_json()
        return {"error": "Could not generate fix"}

    # --- Pipeline Execution ---

    async def execute_pipeline(self, file_path: str, frames: Optional[List[str]] = None) -> Dict[str, Any]:
        """Execute validation pipeline on a file."""
        result, context = await self.pipeline_handler.execute_pipeline(file_path, frames)
        serialized = serialize_pipeline_result(result)
        serialized["context_summary"] = context.get_summary()
        return serialized

    async def execute_pipeline_stream(self, file_path: str, frames: Optional[List[str]] = None, verbose: bool = False) -> AsyncIterator[Dict[str, Any]]:
        """Execute validation pipeline with streaming progress updates."""
        async for event in self.pipeline_handler.execute_pipeline_stream(file_path, frames):
            if event.get("type") == "result":
                result = event["result"]
                context = event["context"]
                event = {
                    "type": "result",
                    "data": {**serialize_pipeline_result(result), "context_summary": context.get_summary()}
                }
            yield event

    async def scan(self, path: str, frames: Optional[List[str]] = None) -> Dict[str, Any]:
        """Legacy scan implementation (for compatibility)."""
        # Simplified scan: execute on directory and return summary
        all_issues = []
        files_scanned = 0
        async for event in self.execute_pipeline_stream(path, frames):
            if event["type"] == "result":
                res = event["data"]
                # Flatten issues for legacy CLI support
                for fr in res.get("frame_results", []):
                    for f in fr.get("findings", []):
                        all_issues.append({
                            "filePath": f.get("file", ""),
                            "severity": f.get("severity", "medium"),
                            "message": f.get("message", ""),
                            "line": f.get("line", 0),
                            "frame": fr.get("frame_id")
                        })
                return {
                    "success": True,
                    "issues": all_issues,
                    "summary": res.get("summary", {}),
                    "duration": res.get("duration", 0)
                }
        return {"success": False, "error": "Scan failed"}

    async def analyze(self, filePath: str) -> Dict[str, Any]:
        """Alias for execute_pipeline."""
        return await self.execute_pipeline(filePath)

    # --- Configuration & Metadata ---

    async def get_config(self) -> Dict[str, Any]:
        """Get Warden and LLM configuration."""
        providers = []
        if self.llm_config:
            for p in self.llm_config.get_all_providers_chain():
                cfg = self.llm_config.get_provider_config(p)
                if cfg and cfg.enabled:
                    providers.append({"name": p.value, "model": cfg.default_model, "enabled": True})

        frames_info = []
        if self.orchestrator:
            from warden.cli_bridge.config_manager import ConfigManager
            config_mgr = ConfigManager(self.project_root)
            for f in self.orchestrator.frames:
                frames_info.append({
                    "id": f.frame_id,
                    "name": f.name,
                    "description": f.description,
                    "enabled": config_mgr.get_frame_status(f.frame_id) is not False
                })

        return {
            "version": "0.1.0",
            "llm_providers": providers,
            "default_provider": self.llm_config.default_provider.value if self.llm_config else "none",
            "frames": frames_info,
            "config_name": self.active_config_name
        }

    async def get_available_frames(self) -> List[Dict[str, Any]]:
        """List all currently active frames with metadata."""
        config = await self.get_config()
        return config["frames"]

    async def update_frame_status(self, frame_id: str, enabled: bool) -> Dict[str, Any]:
        """Update frame status in project config."""
        from warden.cli_bridge.config_manager import ConfigManager
        config_mgr = ConfigManager(self.project_root)
        result = config_mgr.update_frame_status(frame_id, enabled)
        return {"success": True, "frame_id": frame_id, "enabled": enabled}

    # --- LLM Analysis ---

    async def analyze_with_llm(self, prompt: str, provider: Optional[str] = None, stream: bool = True) -> AsyncIterator[str]:
        """Stream LLM analysis response."""
        async for chunk in self.llm_handler.analyze_with_llm(prompt, provider, stream):
            yield chunk

    # --- Tooling & Diagnostics ---

    async def get_available_providers(self) -> List[Dict[str, Any]]:
        """List discoverable AST/LSP providers."""
        return await self.tool_handler.get_available_providers()

    async def test_provider(self, language: str) -> Dict[str, Any]:
        """Test a specific language provider."""
        return await self.tool_handler.test_provider(language)

    async def ping(self) -> Dict[str, str]:
        """Health check."""
        return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}
