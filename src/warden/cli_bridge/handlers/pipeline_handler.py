"""
Pipeline Handler for Warden Bridge.
Handles scanning files and streaming pipeline progress.
"""

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional, AsyncIterator, Union
from warden.shared.infrastructure.logging import get_logger
from warden.cli_bridge.protocol import IPCError, ErrorCode
from warden.validation.domain.frame import CodeFile
from warden.cli_bridge.handlers.base import BaseHandler

logger = get_logger(__name__)

class PipelineHandler(BaseHandler):
    """Handles code scanning and pipeline streaming events."""

    def __init__(self, orchestrator: Any, project_root: Path):
        self.orchestrator = orchestrator
        self.project_root = project_root

    async def execute_pipeline_async(self, file_path: str, frames: Optional[List[str]] = None, analysis_level: str = "standard") -> Dict[str, Any]:
        """Execute validation pipeline on a single file."""
        if not self.orchestrator:
            raise IPCError(ErrorCode.INTERNAL_ERROR, "Pipeline orchestrator not initialized")

        path = Path(file_path)
        if not path.exists():
            raise IPCError(ErrorCode.FILE_NOT_FOUND, f"File not found: {file_path}")

        code_file = CodeFile(
            path=str(path.absolute()),
            content=path.read_text(encoding="utf-8"),
            language=self._detect_language(path),
        )

        result, context = await self.orchestrator.execute_async(
            [code_file], 
            frames_to_execute=frames,
            analysis_level=analysis_level
        )
        
        # Serialization handled by bridge or helper
        return result, context

    async def execute_pipeline_stream_async(self, paths: Union[str, List[str]], frames: Optional[List[str]] = None, analysis_level: str = "standard") -> AsyncIterator[Dict[str, Any]]:
        """Execute validation pipeline with streaming progress updates."""
        if not self.orchestrator:
            raise IPCError(ErrorCode.INTERNAL_ERROR, "Pipeline orchestrator not initialized")

        # Normalize to list
        if isinstance(paths, str):
            path_list = [Path(paths)]
        else:
            path_list = [Path(p) for p in paths]

        code_files = await self._collect_files_async(path_list)
        if not code_files:
            # We don't raise error if empty here, just skip to avoid breaking on partial diffs
            # But if it's a single file request and missing, we might want to warn
            # For now, let's just yield nothing or raise if truly empty request
             # Log warning instead of error to allow partial valid scans
            logger.warning("no_code_files_found", paths=str(paths))
            return 

        progress_queue: asyncio.Queue = asyncio.Queue()
        pipeline_done = asyncio.Event()

        def progress_callback(event: str, data: dict) -> None:
            progress_queue.put_nowait({"type": "progress", "event": event, "data": data})

        # Temporarily swap callback
        original_callback = self.orchestrator.progress_callback
        self.orchestrator.progress_callback = progress_callback

        try:
            # Run in background
            pipeline_task = asyncio.create_task(
                self.orchestrator.execute_async(
                    code_files, 
                    frames_to_execute=frames,
                    analysis_level=analysis_level
                )
            )

            while not pipeline_task.done() or not progress_queue.empty():
                try:
                    event = await asyncio.wait_for(progress_queue.get(), timeout=0.1)
                    yield event
                    if event.get("type") == "result":
                        break
                except asyncio.TimeoutError:
                    continue

            result, context = await pipeline_task
            yield {"type": "result", "result": result, "context": context}

        finally:
            self.orchestrator.progress_callback = original_callback

    async def _collect_files_async(self, paths: List[Path]) -> List[CodeFile]:
        """Collect and prepare code files for pipeline execution using optimized discoverer."""
        from warden.analysis.application.discovery.discoverer import FileDiscoverer
        
        code_files = []
        seen_paths = set()
        
        for root_path in paths:
            if not root_path.exists():
                logger.warning("path_not_found_skipping", path=str(root_path))
                continue
            
            # Get discovery settings from orchestrator config if available
            discovery_config = getattr(self.orchestrator.config, "discovery_config", {}) or {}
            max_size_mb = discovery_config.get("max_size_mb")

            # Fallback to global rules for size limit
            if max_size_mb is None and hasattr(self.orchestrator.config, "global_rules"):
                for rule in self.orchestrator.config.global_rules:
                    if rule.id == "file-size-limit" and rule.enabled:
                        max_size_mb = rule.conditions.get("max_size_mb")
                        if max_size_mb:
                            break

            # Use optimized FileDiscoverer (leverages Rust)
            logger.info("discovery_started_bridge", root=str(root_path), max_size_mb=max_size_mb)
            discoverer = FileDiscoverer(root_path, use_gitignore=True, max_size_mb=max_size_mb)
            discovery_result = await discoverer.discover_async()
            
            for f in discovery_result.get_analyzable_files():
                if f.path in seen_paths:
                    continue
                    
                try:
                    p = Path(f.path)
                    code_files.append(CodeFile(
                        path=str(p.absolute()),
                        content=p.read_text(encoding="utf-8", errors='replace'),
                        language=f.file_type.value,
                        line_count=f.line_count or 0,
                        hash=f.hash,
                        metadata=f.metadata
                    ))
                    seen_paths.add(f.path)
                except Exception as e:
                    logger.warning("file_read_error", file=f.path, error=str(e))
        
        return code_files[:1000] # Limit protection

    def _detect_language(self, path: Path) -> str:
        ext = path.suffix.lower()
        mapping = {
            '.py': 'python', '.js': 'javascript', '.ts': 'typescript',
            '.jsx': 'javascript', '.tsx': 'typescript', '.go': 'go',
            '.rs': 'rust', '.java': 'java', '.cs': 'csharp'
        }
        return mapping.get(ext, 'text')
