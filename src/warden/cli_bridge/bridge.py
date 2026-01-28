"""
Warden Bridge - Core IPC Service

Exposes Warden's Python backend functionality to the Ink CLI through JSON-RPC.
Refactored into modular handlers to maintain < 500 lines per core rules.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, AsyncIterator, Union
from datetime import datetime

from warden.shared.infrastructure.logging import get_logger
from warden.cli_bridge.handlers.config_handler import ConfigHandler
from warden.cli_bridge.handlers.pipeline_handler import PipelineHandler
from warden.cli_bridge.handlers.llm_handler import LLMHandler
from warden.cli_bridge.handlers.tool_handler import ToolHandler
from warden.cli_bridge.utils import serialize_pipeline_result
from warden.shared.utils.path_utils import sanitize_path

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
            llm_service = create_client(self.llm_config.default_provider)
            if llm_service:
                # Attach for tiering awareness
                llm_service.config = self.llm_config
            self.llm_handler = LLMHandler(self.llm_config, llm_service=llm_service)
        except Exception as e:
            logger.warning("llm_init_failed_in_bridge", error=str(e))
            self.llm_config = None
            self.llm_handler = None
            llm_service = None

        # Load pipeline configuration and frames
        config_data = self.config_handler.load_pipeline_config(config_path)
        self.active_config_name = config_data["name"]

        # Initialize Rate Limiter (Centralized to prevent Event Loop issues)
        from warden.llm.rate_limiter import RateLimiter, RateLimitConfig
        import os
        
        # Load limits from env or use defaults
        tpm = int(os.getenv("WARDEN_LIMIT_TPM", "5000"))
        rpm = int(os.getenv("WARDEN_LIMIT_RPM", "10"))
        burst = int(os.getenv("WARDEN_LIMIT_BURST", "1"))
        
        self.rate_limiter = RateLimiter(RateLimitConfig(tpm=tpm, rpm=rpm, burst=burst))

        # Initialize Orchestrator
        from warden.pipeline.application.phase_orchestrator import PhaseOrchestrator
        self.orchestrator = PhaseOrchestrator(
            frames=config_data["frames"],
            config=config_data["config"],
            llm_service=llm_service,
            available_frames=config_data["available_frames"],
            rate_limiter=self.rate_limiter
        )
        
        self.pipeline_handler = PipelineHandler(self.orchestrator, self.project_root)
        self.config_handler.validate_consistency()
        
        # Store LLM service for semantic tools
        self.llm_service = llm_service

        logger.info("warden_bridge_initialized", config=self.active_config_name, orchestrator=self.orchestrator is not None)

    # --- Semantic Fixes ---

    async def request_fix_async(self, file_path: str, line_number: int, issue_type: str, context_code: str = "") -> Dict[str, Any]:
        """Request a semantic fix for a vulnerability."""
        from warden.fortification.application.fortification_phase import FortificationPhase
        
        # Sanitize path
        safe_path = sanitize_path(file_path, self.project_root)
        
        # Create minimal context for fortification
        context = {
            "project_root": self.project_root,
            "language": self.pipeline_handler._detect_language(safe_path),
            "project_type": "unknown", # Could be detected
            "framework": "unknown"     # Could be detected
        }
        
        # Initialize phase with LLM service
        FortificationPhase(
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
        
        fix = await generator.generate_fortification_async(
            finding=finding,
            code_context=context_code,
            framework=context["framework"],
            language=context["language"]
        )
        
        if fix:
            return fix.to_json()
        return {"error": "Could not generate fix"}

    # --- Pipeline Execution ---

    async def execute_pipeline_async(self, file_path: str, frames: Optional[List[str]] = None, analysis_level: str = "standard") -> Dict[str, Any]:
        """Execute validation pipeline on a file."""
        result, context = await self.pipeline_handler.execute_pipeline_async(file_path, frames, analysis_level)
        serialized = serialize_pipeline_result(result)
        serialized["context_summary"] = context.get_summary()
        return serialized

    async def execute_pipeline_stream_async(self, file_path: Union[str, List[str]], frames: Optional[List[str]] = None, verbose: bool = False, analysis_level: str = "standard", ci_mode: bool = False) -> AsyncIterator[Dict[str, Any]]:
        """Execute validation pipeline with streaming progress updates."""
        # Set CI mode on orchestrator config
        if ci_mode:
            self.orchestrator.config.ci_mode = True

        async for event in self.pipeline_handler.execute_pipeline_stream_async(file_path, frames, analysis_level):
            if event.get("type") == "result":
                result = event["result"]
                context = event["context"]
                event = {
                    "type": "result",
                    "data": {**serialize_pipeline_result(result), "context_summary": context.get_summary()}
                }
            yield event

    async def scan_async(self, path: str, frames: Optional[List[str]] = None) -> Dict[str, Any]:
        """Legacy scan implementation (for compatibility)."""
        # Simplified scan: execute on directory and return summary
        all_issues = []
        last_summary = {}
        last_duration = 0
        async for event in self.execute_pipeline_stream_async(path, frames):
            if event["type"] == "result":
                res = event["data"]
                last_summary = res.get("summary", {})
                last_duration = res.get("duration", 0)
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
        
        if not all_issues and not last_summary:
            return {"success": False, "error": "Scan failed or no files found"}

        return {
            "success": True,
            "issues": all_issues,
            "summary": last_summary,
            "duration": last_duration
        }

    async def analyze_async(self, filePath: str) -> Dict[str, Any]:
        """Alias for execute_pipeline."""
        return await self.execute_pipeline_async(filePath)

    # --- Configuration & Metadata ---

    async def get_config_async(self) -> Dict[str, Any]:
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

    async def get_available_frames_async(self) -> List[Dict[str, Any]]:
        """List all currently active frames with metadata."""
        config = await self.get_config_async()
        return config["frames"]

    async def update_frame_status_async(self, frame_id: str, enabled: bool) -> Dict[str, Any]:
        """Update frame status in project config."""
        from warden.cli_bridge.config_manager import ConfigManager
        config_mgr = ConfigManager(self.project_root)
        config_mgr.update_frame_status_async(frame_id, enabled)
        return {"success": True, "frame_id": frame_id, "enabled": enabled}

    # --- LLM Analysis ---

    async def analyze_with_llm_async(self, prompt: str, provider: Optional[str] = None, stream: bool = True) -> AsyncIterator[str]:
        """Stream LLM analysis response."""
        async for chunk in self.llm_handler.analyze_with_llm_async(prompt, provider, stream):
            yield chunk

    # --- Tooling & Diagnostics ---

    async def get_available_providers_async(self) -> List[Dict[str, Any]]:
        """List discoverable AST/LSP providers."""
        return await self.tool_handler.get_available_providers_async()

    async def test_provider_async(self, language: str) -> Dict[str, Any]:
        """Test a specific language provider."""
        return await self.tool_handler.test_provider(language)

    async def ping_async(self) -> Dict[str, str]:
        """Health check."""
        return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}

 
 
 
# CACHE_BUST_1768315992
