"""
Pipeline Handler for Warden Bridge.
Handles scanning files and streaming pipeline progress.
"""

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional, AsyncIterator
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

    async def execute_pipeline(self, file_path: str, frames: Optional[List[str]] = None) -> Dict[str, Any]:
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

        result, context = await self.orchestrator.execute([code_file], frames_to_execute=frames)
        
        # Serialization handled by bridge or helper
        return result, context

    async def execute_pipeline_stream(self, file_path: str, frames: Optional[List[str]] = None) -> AsyncIterator[Dict[str, Any]]:
        """Execute validation pipeline with streaming progress updates."""
        if not self.orchestrator:
            raise IPCError(ErrorCode.INTERNAL_ERROR, "Pipeline orchestrator not initialized")

        path = Path(file_path)
        if not path.exists():
            raise IPCError(ErrorCode.FILE_NOT_FOUND, f"File not found: {file_path}")

        code_files = self._collect_files(path)
        if not code_files:
            raise IPCError(ErrorCode.INVALID_PARAMS, f"No supported code files found in: {file_path}")

        progress_queue: asyncio.Queue = asyncio.Queue()
        pipeline_done = asyncio.Event()

        def progress_callback(event: str, data: dict) -> None:
            progress_queue.put_nowait({"type": "progress", "event": event, "data": data})

        # Temporarily swap callback
        original_callback = self.orchestrator.progress_callback
        self.orchestrator.progress_callback = progress_callback

        try:
            # Run in background
            pipeline_task = asyncio.create_task(self.orchestrator.execute(code_files, frames_to_execute=frames))

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

    def _collect_files(self, path: Path) -> List[CodeFile]:
        # Logic from bridge.py lines 596-678
        from warden.shared.infrastructure.ignore_matcher import IgnoreMatcher
        
        code_extensions = {'.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.cs', '.go', '.rs', '.cpp', '.c', '.h'}
        use_gitignore = getattr(self.orchestrator.config, 'use_gitignore', True) if self.orchestrator else True
        ignore_matcher = IgnoreMatcher(self.project_root, use_gitignore=use_gitignore)
        
        files_to_scan = []
        if path.is_file():
            files_to_scan = [path]
        else:
            for item in path.rglob("*"):
                if item.is_file() and item.suffix in code_extensions:
                    if any(ignore_matcher.should_ignore_directory(p) for p in item.parts):
                        continue
                    if ignore_matcher.should_ignore_path(item):
                        continue
                    files_to_scan.append(item)

        code_files = []
        for p in files_to_scan[:1000]: # Limit protection
            try:
                code_files.append(CodeFile(
                    path=str(p.absolute()),
                    content=p.read_text(encoding="utf-8", errors='replace'),
                    language=self._detect_language(p),
                ))
            except Exception as e:
                logger.warning("file_read_error", file=str(p), error=str(e))
        return code_files

    def _detect_language(self, path: Path) -> str:
        ext = path.suffix.lower()
        mapping = {
            '.py': 'python', '.js': 'javascript', '.ts': 'typescript',
            '.jsx': 'javascript', '.tsx': 'typescript', '.go': 'go',
            '.rs': 'rust', '.java': 'java', '.cs': 'csharp'
        }
        return mapping.get(ext, 'text')
