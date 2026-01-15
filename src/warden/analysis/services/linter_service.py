"""
Linter Service.

Provides a unified interface for code quality tools (Ruff, Biome, etc.).
Designed for resilience, performance, and detailed reporting.
"""

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

from warden.shared.infrastructure.logging import get_logger
from warden.validation.domain.frame import Finding, CodeFile
from warden.analysis.domain.project_context import ProjectContext
from warden.ast.domain.enums import CodeLanguage

logger = get_logger(__name__)


@dataclass
class LinterMetrics:
    """Standardized linter metrics."""
    tool: str
    total_errors: int
    blocker_count: int
    fixable_count: int
    scan_duration: float
    is_available: bool = True
    error_message: Optional[str] = None


class ILinterProvider(Protocol):
    """Protocol for linter tool adapters (SOLID: Open/Closed)."""
    
    @property
    def name(self) -> str: ...
    @property
    def languages(self) -> List[CodeLanguage]: ...

    async def detect_async(self, context: ProjectContext) -> bool:
        """Check availability and configuration."""
        ...

    async def run_metrics_async(self, files: List[Path]) -> LinterMetrics:
        """Fast scan for quality metrics."""
        ...

    async def run_findings_async(self, files: List[Path]) -> List[Finding]:
        """Detailed scan for actionable findings."""
        ...



class FrameLinterAdapter:
    """Adapts a ValidationFrame to the ILinterProvider protocol."""
    
    def __init__(self, frame: Any):
        self.frame = frame
        self._name = frame.name
        # Heuristic: Detect supported languages from frame ID
        self._languages = []
        fid = frame.frame_id.lower()
        if "python" in fid:
            self._languages.append(CodeLanguage.PYTHON)
        elif "javascript" in fid or "js" in fid:
            self._languages.append(CodeLanguage.JAVASCRIPT)
        elif "typescript" in fid or "ts" in fid:
            self._languages.append(CodeLanguage.TYPESCRIPT)
        elif "rust" in fid:
            self._languages.append(CodeLanguage.RUST)
        elif "go" in fid:
            self._languages.append(CodeLanguage.GO)
        
        # If no specific language detected, assume it supports all (let frame filter)
        if not self._languages:
            self._languages = [CodeLanguage.UNKNOWN]

    @property
    def name(self) -> str:
        return self._name

    @property
    def languages(self) -> List[CodeLanguage]:
        return self._languages

    async def detect_async(self, context: ProjectContext) -> bool:
        """Delegate to frame.detect_async if available, else True."""
        if hasattr(self.frame, 'detect_async'):
            return await self.frame.detect_async()
        return True

    def _path_to_codefile(self, path: Path) -> CodeFile:
        """Helper to create CodeFile with simple language guess."""
        ext = path.suffix.lower()
        lang = "unknown"
        if ext == ".py": lang = "python"
        elif ext == ".js": lang = "javascript"
        elif ext == ".ts": lang = "typescript"
        elif ext == ".rs": lang = "rust"
        elif ext == ".go": lang = "go"
        elif ext == ".java": lang = "java"
        # ... add more as needed or rely on frame to check path
        
        return CodeFile(path=str(path), content="", language=lang)

    async def run_metrics_async(self, files: List[Path]) -> LinterMetrics:
        """Run frame and extract metrics."""
        # Convert Paths to dummy CodeFiles
        code_files = [self._path_to_codefile(p) for p in files]
        
        start_time = asyncio.get_event_loop().time()
        result = await self.frame.execute_async(code_files)
        duration = asyncio.get_event_loop().time() - start_time
        
        # Safe extraction
        issues = result.issues_found
        # We don't have explicit blocker count in basic result easily without iterating
        blockers = sum(1 for f in result.findings if f.is_blocker)
        
        return LinterMetrics(
            tool=self.name,
            total_errors=issues,
            blocker_count=blockers,
            fixable_count=0, # Not reported yet
            scan_duration=duration,
            is_available=True
        )

    async def run_findings_async(self, files: List[Path]) -> List[Finding]:
        """Run frame and return findings."""
        code_files = [self._path_to_codefile(p) for p in files]
        result = await self.frame.execute_async(code_files)
        return result.findings


class LinterService:
    """
    Service facade for all linter interactions.
    Manages detection, metrics, and finding aggregation across multiple providers.
    
    Refactored: Now delegates to installed Hub Frames via Registry.
    """

    def __init__(self):
        self.providers: List[ILinterProvider] = []
        self.active_providers: List[ILinterProvider] = []
        self._initialize_providers()

    def _initialize_providers(self):
        """Dynamic discovery of linter frames from Registry."""
        try:
            from warden.validation.infrastructure.frame_registry import FrameRegistry
            from warden.validation.domain.enums import FrameCategory
            
            registry = FrameRegistry()
            # Get all frames, filter for LANGUAGE_SPECIFIC or those named '*lint*'
            # For MVP, specifically looking for python_lint
            frames = registry.discover_all()
            
            for frame_cls in frames:
                try:
                    # Instantiate frame
                    frame = frame_cls()
                    
                    # Heuristic: Is this a linter?
                    # Check category or name
                    is_linter = (frame.category == FrameCategory.LANGUAGE_SPECIFIC) or ("lint" in frame.frame_id)
                    
                    if is_linter:
                        adapter = FrameLinterAdapter(frame)
                        self.providers.append(adapter)
                        logger.info("linter_provider_registered", name=frame.name, frame_id=frame.frame_id)
                except Exception as e:
                    logger.warning("linter_provider_load_failed", frame=str(frame_cls), error=str(e))
                    
        except ImportError:
            logger.warning("frame_registry_not_available_skipping_linters")
        except Exception as e:
            logger.error("linter_service_init_failed", error=str(e))

    async def detect_and_setup(self, context: ProjectContext) -> Dict[str, bool]:
        """
        Detect applicable linters for the project context.
        Returns: Dict of tool_name -> is_available
        """
        results = {}
        self.active_providers = []
        
        for provider in self.providers:
            try:
                available = await provider.detect_async(context)
                results[provider.name] = available
                if available:
                    self.active_providers.append(provider)
            except Exception as e:
                logger.warning("linter_detection_error", provider=provider.name, error=str(e))
                results[provider.name] = False
        
        logger.info("active_linters_setup", count=len(self.active_providers), tools=list(results.keys()))
        return results

    async def run_metrics(self, code_files: List[CodeFile]) -> Dict[str, LinterMetrics]:
        """Aggregate metrics from all active providers."""
        metrics = {}
        
        # Optimization: Don't group by language yet, assume providers handle specific files
        # But providers expect generic paths.
        all_paths = [Path(cf.path) for cf in code_files]
        
        for provider in self.active_providers:
            try:
                # Naive: pass all paths to provider, assuming it filters internally or Adapter handles it
                # Our PythonLinterFrame filters by extension `.py` so it's safe.
                metrics[provider.name] = await provider.run_metrics_async(all_paths)
            except Exception as e:
                logger.error("linter_metrics_failed", provider=provider.name, error=str(e))
                metrics[provider.name] = LinterMetrics(
                    tool=provider.name, total_errors=0, blocker_count=0, fixable_count=0, scan_duration=0.0,
                    is_available=False, error_message=str(e)
                )
        
        return metrics

    async def run_findings(self, code_files: List[CodeFile]) -> List[Finding]:
        """Aggregate findings from all active providers."""
        all_findings = []
        all_paths = [Path(cf.path) for cf in code_files]

        for provider in self.active_providers:
            try:
                findings = await provider.run_findings_async(all_paths)
                all_findings.extend(findings)
            except Exception as e:
                logger.error("linter_findings_failed", provider=provider.name, error=str(e))
                
        return all_findings

    def _group_files(self, code_files: List[CodeFile]) -> Dict[CodeLanguage, List[Path]]:
        # Legacy helper, kept if needed but currently unused in simplification
        return {}

    def _map_lang_string(self, lang_str: str, path: str) -> Optional[CodeLanguage]:
        return None

