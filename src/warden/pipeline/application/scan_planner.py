"""
Scan Planner — pre-scan analysis strategy.

Runs a lightweight planning step *before* the actual scan to give the user
visibility into:
  - Which frames will be executed and why
  - How many files will be scanned
  - An estimate of LLM calls required
  - Which files will be skipped (gitignored, binary, too large, etc.)
  - Human-readable reasoning for each frame selection

Usage:
    planner = ScanPlanner()
    plan = await planner.plan(project_root=Path("."), config=pipeline_config)
    # plan is a ScanPlan dataclass
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Domain model
# ---------------------------------------------------------------------------


@dataclass
class FramePlan:
    """Details about one frame that will be executed."""

    frame_id: str
    display_name: str
    reason: str
    is_llm_powered: bool = False
    estimated_calls: int = 0
    description: str = ""


@dataclass
class ScanPlan:
    """
    Result of the pre-scan planning phase.

    Attributes:
        frames: Frames that will be executed with per-frame reasoning.
        file_count: Number of analysable files that will be scanned.
        estimated_llm_calls: Estimated total LLM calls across all frames.
        skipped_count: Files that will be skipped (gitignored, binary, etc.).
        reasoning: High-level explanation of the selected strategy.
        project_root: The resolved project root used for planning.
        analysis_level: The analysis level that will be used.
    """

    frames: list[FramePlan] = field(default_factory=list)
    file_count: int = 0
    estimated_llm_calls: int = 0
    skipped_count: int = 0
    reasoning: str = ""
    project_root: str = ""
    analysis_level: str = "standard"
    max_files: int = 1000


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------


class ScanPlanner:
    """
    Generates a ScanPlan without executing the scan.

    The planner performs:
    1. File discovery (respecting .gitignore and binary detection).
    2. Frame registry lookup to identify candidate frames.
    3. LLM-call estimation based on analysis level and file count.
    """

    # Rough multipliers for LLM call estimation per frame per file.
    # "basic" level skips LLM entirely; "standard" does one pass; "deep" does two.
    _LLM_CALLS_PER_FILE: dict[str, float] = {
        "basic": 0.0,
        "standard": 1.0,
        "deep": 2.0,
    }

    async def plan(
        self,
        project_root: Path,
        config: Any | None = None,
        max_files: int | None = None,
    ) -> ScanPlan:
        """
        Produce a ScanPlan for *project_root* using *config*.

        Args:
            project_root: Directory to scan.
            config: Optional PipelineConfig. When None, a minimal default is
                    used so that the planner is callable in tests without a
                    fully initialised pipeline.

        Returns:
            ScanPlan with all planning fields populated.
        """
        project_root = Path(project_root).resolve()

        # Determine analysis level
        analysis_level = "standard"
        use_gitignore = True

        if config is not None:
            try:
                analysis_level = config.analysis_level.value
            except AttributeError:
                analysis_level = getattr(config, "analysis_level", "standard")
            use_gitignore = getattr(config, "use_gitignore", True)

        # ---- File discovery ----
        file_count, skipped_count = await self._discover_files(project_root, use_gitignore)

        # ---- Frame selection ----
        frames = self._select_frames(analysis_level, file_count)

        # ---- LLM call estimation ----
        llm_factor = self._LLM_CALLS_PER_FILE.get(analysis_level, 1.0)
        llm_frames = [f for f in frames if f.is_llm_powered]
        estimated_llm_calls = int(file_count * llm_factor * max(len(llm_frames), 1))

        # ---- High-level reasoning ----
        reasoning = self._build_reasoning(analysis_level, file_count, frames, skipped_count)

        # Resolve max_files: explicit arg > config > default
        resolved_max_files = max_files
        if resolved_max_files is None:
            try:
                from warden.pipeline.validators.input_validator import PipelineInput
                resolved_max_files = PipelineInput().max_files
            except Exception:
                resolved_max_files = 1000

        return ScanPlan(
            frames=frames,
            file_count=file_count,
            estimated_llm_calls=estimated_llm_calls,
            skipped_count=skipped_count,
            reasoning=reasoning,
            project_root=str(project_root),
            analysis_level=analysis_level,
            max_files=resolved_max_files,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _discover_files(self, project_root: Path, use_gitignore: bool) -> tuple[int, int]:
        """
        Run lightweight async file discovery.

        Returns:
            (analysable_file_count, skipped_file_count)
        """
        try:
            from warden.analysis.application.discovery.discoverer import FileDiscoverer

            discoverer = FileDiscoverer(
                root_path=project_root,
                use_gitignore=use_gitignore,
            )
            result = await discoverer.discover_async()
            analysable = result.stats.analyzable_files
            total = result.stats.total_files
            skipped = total - analysable
            return analysable, max(skipped, 0)
        except Exception as exc:
            logger.warning("scan_planner_discovery_failed", error=str(exc))
            # Fall back to a simple recursive count so the planner still works
            return self._fallback_file_count(project_root)

    def _fallback_file_count(self, project_root: Path) -> tuple[int, int]:
        """Simple sync fallback when the full discoverer is unavailable."""
        _CODE_SUFFIXES = {
            ".py", ".js", ".ts", ".tsx", ".jsx",
            ".go", ".rs", ".java", ".kt", ".swift",
            ".rb", ".php", ".c", ".cpp", ".cs",
            ".sh", ".sql", ".yaml", ".yml",
        }
        total = 0
        skipped = 0
        try:
            for path in project_root.rglob("*"):
                if not path.is_file():
                    continue
                # Skip hidden directories (.git, .venv, __pycache__, node_modules)
                parts = path.relative_to(project_root).parts
                if any(p.startswith(".") or p in ("node_modules", "__pycache__", ".venv", "venv") for p in parts):
                    skipped += 1
                    continue
                if path.suffix in _CODE_SUFFIXES:
                    total += 1
                else:
                    skipped += 1
        except Exception:
            pass
        return total, skipped

    def _select_frames(self, analysis_level: str, file_count: int) -> list[FramePlan]:
        """
        Determine which frames will run for the given analysis level.

        Falls back to a curated static list if the registry is unavailable.
        """
        try:
            return self._frames_from_registry(analysis_level)
        except Exception as exc:
            logger.debug("scan_planner_registry_failed", error=str(exc))
            return self._static_frames(analysis_level)

    def _frames_from_registry(self, analysis_level: str) -> list[FramePlan]:
        """Load frames from the live FrameRegistry."""
        from warden.validation.infrastructure.frame_registry import FrameRegistry

        registry = FrameRegistry()
        all_frames = registry.get_all_frames_as_dict()

        plans: list[FramePlan] = []
        for frame_id, frame_cls in all_frames.items():
            # Determine if this frame uses LLM
            is_llm = getattr(frame_cls, "uses_llm", False)

            # Skip heavy LLM frames in basic mode
            if analysis_level == "basic" and is_llm:
                continue

            reason = self._frame_reason(frame_id, analysis_level)
            description = getattr(frame_cls, "description", "") or ""
            plans.append(
                FramePlan(
                    frame_id=frame_id,
                    display_name=getattr(frame_cls, "display_name", frame_id),
                    reason=reason,
                    is_llm_powered=is_llm,
                    estimated_calls=1 if is_llm else 0,
                    description=description,
                )
            )

        return plans

    def _static_frames(self, analysis_level: str) -> list[FramePlan]:
        """Curated fallback frame list when registry is unavailable."""
        base_frames = [
            FramePlan("secrets", "Secret Detection", "Detects hardcoded secrets and API keys.", False, 0, "Detects hardcoded secrets and API keys."),
            FramePlan("injection", "Injection Analysis", "Detects SQL, command, and code injection.", False, 0, "Detects SQL, command, and code injection vulnerabilities."),
            FramePlan("xss", "XSS Detection", "Detects cross-site scripting vulnerabilities.", False, 0, "Detects cross-site scripting vulnerabilities."),
            FramePlan("auth", "Authentication Audit", "Reviews authentication and authorisation flows.", False, 0, "Reviews authentication and authorisation flows."),
        ]
        llm_frames = [
            FramePlan("semantic", "Semantic Analysis", "LLM-powered context-aware code review.", True, 1, "LLM-powered context-aware code review."),
            FramePlan("logic", "Logic Flow Analysis", "LLM-powered business logic validation.", True, 1, "LLM-powered business logic validation."),
        ]
        deep_frames = [
            FramePlan("taint", "Taint Analysis", "Deep data flow taint tracking.", True, 2, "Deep data flow taint tracking across files."),
        ]

        if analysis_level == "basic":
            return base_frames
        if analysis_level == "standard":
            return base_frames + llm_frames
        # deep
        return base_frames + llm_frames + deep_frames

    def _frame_reason(self, frame_id: str, analysis_level: str) -> str:
        """Generate a short reason string for frame selection."""
        level_reasons = {
            "basic": "selected for deterministic analysis (no LLM required)",
            "standard": "selected for standard AI-assisted analysis",
            "deep": "selected for comprehensive deep security audit",
        }
        return f"Frame '{frame_id}' {level_reasons.get(analysis_level, 'included in scan plan')}."

    def _build_reasoning(
        self,
        analysis_level: str,
        file_count: int,
        frames: list[FramePlan],
        skipped_count: int,
    ) -> str:
        """Produce a human-readable strategy explanation."""
        llm_powered = sum(1 for f in frames if f.is_llm_powered)
        deterministic = len(frames) - llm_powered

        level_descriptions = {
            "basic": "Basic mode — only deterministic (regex/AST) frames run, no LLM calls.",
            "standard": "Standard mode — deterministic frames plus LLM-assisted analysis for deeper insights.",
            "deep": "Deep mode — full semantic analysis, taint tracking, and multi-pass LLM review.",
        }

        desc = level_descriptions.get(analysis_level, "Analysis plan generated.")
        return (
            f"{desc} "
            f"{file_count} file(s) will be scanned using {len(frames)} frame(s) "
            f"({deterministic} deterministic, {llm_powered} LLM-powered). "
            f"{skipped_count} file(s) skipped (gitignored, binary, or non-code)."
        )
