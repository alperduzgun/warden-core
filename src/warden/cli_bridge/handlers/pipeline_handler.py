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
from warden.shared.utils.path_utils import sanitize_path

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

        try:
            path = sanitize_path(file_path, self.project_root)
        except ValueError as e:
            raise IPCError(ErrorCode.VALIDATION_ERROR, str(e))

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

        # 1. Normalize to list and sanitize
        try:
            if isinstance(paths, str):
                path_list = [sanitize_path(paths, self.project_root)]
            else:
                path_list = [sanitize_path(p, self.project_root) for p in paths]
        except ValueError as e:
            raise IPCError(ErrorCode.VALIDATION_ERROR, str(e))

        # 2. Collect files first to detect languages
        code_files = await self._collect_files_async(path_list)
        if not code_files:
            logger.warning("no_code_files_found", paths=str(paths))
            return 

        # 3. Detect required languages
        required_languages = {cf.language.upper() for cf in code_files if cf.language}
        
        # 4. Check for environment dependencies (Targeted Auto-Grammar Installation)
        try:
            await self._ensure_dependencies_async(required_languages)
        except Exception as e:
            logger.warning("dependency_check_failed", error=str(e))

        progress_queue: asyncio.Queue = asyncio.Queue()
        asyncio.Event()

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

    async def _ensure_dependencies_async(self, target_languages: Optional[set] = None) -> None:
        """Detect missing platform/language dependencies and attempt auto-install."""
        from warden.ast.application.provider_registry import ASTProviderRegistry
        from warden.ast.providers.tree_sitter_provider import TreeSitterProvider
        from warden.services.dependencies.dependency_manager import DependencyManager
        
        logger.info("checking_environment_dependencies")
        
        # 1. Initialize Registry and discover providers
        registry = ASTProviderRegistry()
        await registry.discover_providers()
        
        # 2. Extract missing grammars from TreeSitterProvider
        ts_provider = registry.get_provider_by_name("tree-sitter")
        if not ts_provider or not isinstance(ts_provider, TreeSitterProvider):
            return
            
        missing_pkgs = ts_provider.missing_grammars
        if not missing_pkgs:
            return
            
        # 3. Filter missing based on project languages (Optimization)
        # TreeSitterProvider.missing_grammars returns 'tree-sitter-lang'
        # We need to map back or filter the languages
        to_install = []
        for pkg in missing_pkgs:
            # Simple heuristic: pkg name ends with -lang, and target_languages has LANG
            lang_part = pkg.replace("tree-sitter-", "").replace("-", "_").upper()
            if target_languages is None or lang_part in target_languages:
                to_install.append(pkg)
            elif lang_part == "C_SHARP" and "CSHARP" in target_languages:
                to_install.append(pkg)
            elif lang_part == "BASH" and "SHELL" in target_languages:
                to_install.append(pkg)

        if not to_install:
            return
            
        # 4. Use DependencyManager to install
        dep_mgr = DependencyManager()
        logger.info("targeted_missing_grammars_detected", packages=to_install)
        
        # For grammars, we explicitly allow system break as they are critical
        success = await dep_mgr.install_packages_async(to_install, allow_system_break=True)
        if success:
            logger.info("missing_grammars_installed_successfully")
        else:
            logger.warning("some_grammars_failed_to_install")
