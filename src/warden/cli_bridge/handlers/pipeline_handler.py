"""
Pipeline Handler for Warden Bridge.
Handles scanning files and streaming pipeline progress.
"""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from warden.cli_bridge.handlers.base import BaseHandler
from warden.cli_bridge.protocol import ErrorCode, IPCError
from warden.shared.infrastructure.logging import get_logger
from warden.shared.utils.path_utils import sanitize_path
from warden.validation.domain.frame import CodeFile

logger = get_logger(__name__)


class PipelineHandler(BaseHandler):
    """Handles code scanning and pipeline streaming events."""

    def __init__(self, orchestrator: Any, project_root: Path):
        self.orchestrator = orchestrator
        self.project_root = project_root

    async def execute_pipeline_async(
        self, file_path: str, frames: list[str] | None = None, analysis_level: str = "standard"
    ) -> dict[str, Any]:
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
            [code_file], frames_to_execute=frames, analysis_level=analysis_level
        )

        # Serialization handled by bridge or helper
        return result, context

    async def execute_pipeline_stream_async(
        self,
        paths: str | list[str],
        frames: list[str] | None = None,
        analysis_level: str = "standard",
        baseline_fingerprints: set | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
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

        # Emit discovery info immediately
        yield {"type": "progress", "event": "discovery_complete", "data": {"total_files": len(code_files)}}

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
                self.orchestrator.execute_async(code_files, frames_to_execute=frames, analysis_level=analysis_level)
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

            # Apply Baseline Filtering (Delta Analysis)
            if baseline_fingerprints:
                result = self._filter_result(result, baseline_fingerprints)

            yield {"type": "result", "result": result, "context": context}

        finally:
            self.orchestrator.progress_callback = original_callback

    async def _collect_files_async(self, paths: list[Path]) -> list[CodeFile]:
        """Collect and prepare code files for pipeline execution using optimized discoverer."""
        from warden.analysis.application.discovery.discoverer import FileDiscoverer

        code_files = []
        seen_paths = set()

        for root_path in paths:
            if not root_path.exists():
                logger.warning("path_not_found_skipping", path=str(root_path))
                continue

            # If it's a file, handle it directly
            if root_path.is_file():
                try:
                    code_files.append(
                        CodeFile(
                            path=str(root_path.absolute()),
                            content=root_path.read_text(encoding="utf-8", errors="replace"),
                            language=self._detect_language(root_path),
                        )
                    )
                    seen_paths.add(str(root_path.absolute()))
                except Exception as e:
                    logger.warning("file_read_error", file=str(root_path), error=str(e))
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
                    code_files.append(
                        CodeFile(
                            path=str(p.absolute()),
                            content=p.read_text(encoding="utf-8", errors="replace"),
                            language=f.file_type.value,
                            line_count=f.line_count or 0,
                            hash=f.hash,
                            metadata=f.metadata,
                        )
                    )
                    seen_paths.add(f.path)
                except Exception as e:
                    logger.warning("file_read_error", file=f.path, error=str(e))

        return code_files[:1000]  # Limit protection

    def _detect_language(self, path: Path) -> str:
        ext = path.suffix.lower()
        mapping = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".jsx": "javascript",
            ".tsx": "typescript",
            ".go": "go",
            ".rs": "rust",
            ".java": "java",
            ".cs": "csharp",
        }
        return mapping.get(ext, "text")

    def _filter_result(self, result: Any, baseline_fingerprints: set) -> Any:
        """Filter out findings that match the baseline fingerprints."""
        import hashlib

        filtered_count = 0

        # Determine how to iterate based on result type
        # Assuming result has 'frame_results' or 'findings'
        # Since result is likely a Pydantic model or dict, access attribute or key

        frame_results = getattr(result, "frame_results", [])
        if not frame_results and isinstance(result, dict):
            frame_results = result.get("frame_results", [])

        for frame in frame_results:
            findings = getattr(frame, "findings", [])
            if not findings and isinstance(frame, dict):
                findings = frame.get("findings", [])

            new_findings = []
            for f in findings:
                # Resolve attributes (Handle both Dict and Finding objects)
                is_dict = isinstance(f, dict)

                if is_dict:
                    rule_id = f.get("id") or f.get("rule_id") or f.get("ruleId", "unknown")
                    location = f.get("location", "")
                    msg = f.get("message", "")
                    raw_path = f.get("file_path") or f.get("path") or f.get("file")
                else:
                    rule_id = getattr(f, "id", None) or getattr(f, "rule_id", None) or getattr(f, "ruleId", "unknown")
                    location = getattr(f, "location", "")
                    msg = getattr(f, "message", "")
                    raw_path = getattr(f, "file_path", None) or getattr(f, "path", None) or getattr(f, "file", None)

                # Resolve file path relative to project root
                path_str = str(raw_path) if raw_path else ""

                # If path missing, try to extract from location
                if not path_str and location:
                    path_str = location.split(":")[0]

                if str(self.project_root) in path_str:
                    rel_path = path_str.replace(str(self.project_root) + "/", "")
                else:
                    rel_path = path_str

                # Include code snippet to distinguish findings in same file
                if is_dict:
                    snippet = f.get("code_snippet") or f.get("codeSnippet") or f.get("code", "")
                else:
                    snippet = (
                        getattr(f, "code_snippet", None) or getattr(f, "codeSnippet", None) or getattr(f, "code", "")
                    )

                composite = f"{rule_id}:{rel_path}:{msg}:{snippet}"
                fp = hashlib.sha256(composite.encode()).hexdigest()

                if fp in baseline_fingerprints:
                    filtered_count += 1
                    # Skip (Filter out)
                else:
                    new_findings.append(f)

            # Update frame with filtered findings
            if isinstance(frame, dict):
                frame["findings"] = new_findings
            else:
                frame.findings = new_findings

        if filtered_count > 0:
            logger.info("baseline_filtered_findings", count=filtered_count)

        return result

    async def _ensure_dependencies_async(self, target_languages: set | None = None) -> None:
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
            if (
                target_languages is None
                or lang_part in target_languages
                or (lang_part == "C_SHARP" and "CSHARP" in target_languages)
                or (lang_part == "BASH" and "SHELL" in target_languages)
            ):
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
