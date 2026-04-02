"""
Unit tests for warden.pipeline.application.scan_planner.

Tests cover:
- ScanPlan dataclass field defaults
- ScanPlanner.plan() with mocked discovery: file/skipped counts propagate
- ScanPlanner.plan() with no config (None) uses sensible defaults
- ScanPlanner.plan() analysis_level propagation
- LLM call estimation for each level
- Frame selection by analysis level
- Fallback file count when discoverer unavailable
- _build_reasoning produces non-empty string
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from warden.pipeline.application.scan_planner import (
    FramePlan,
    ScanPlan,
    ScanPlanner,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_discovery_result(analyzable: int = 10, total: int = 15) -> MagicMock:
    """Build a mock DiscoveryResult with the given file counts."""
    stats = MagicMock()
    stats.analyzable_files = analyzable
    stats.total_files = total
    result = MagicMock()
    result.stats = stats
    return result


class _Config:
    """Minimal config stub."""

    def __init__(self, level: str = "standard", use_gitignore: bool = True):
        class _Level:
            value = level

        self.analysis_level = _Level()
        self.use_gitignore = use_gitignore


# ---------------------------------------------------------------------------
# ScanPlan dataclass
# ---------------------------------------------------------------------------


class TestScanPlanDefaults:
    def test_default_file_count_zero(self):
        plan = ScanPlan()
        assert plan.file_count == 0

    def test_default_frames_empty(self):
        plan = ScanPlan()
        assert plan.frames == []

    def test_default_estimated_llm_calls_zero(self):
        plan = ScanPlan()
        assert plan.estimated_llm_calls == 0

    def test_default_skipped_count_zero(self):
        plan = ScanPlan()
        assert plan.skipped_count == 0

    def test_default_analysis_level(self):
        plan = ScanPlan()
        assert plan.analysis_level == "standard"


# ---------------------------------------------------------------------------
# FramePlan dataclass
# ---------------------------------------------------------------------------


class TestFramePlan:
    def test_frame_plan_attributes(self):
        fp = FramePlan(
            frame_id="secrets",
            display_name="Secret Detection",
            reason="Detects hardcoded keys",
            is_llm_powered=False,
            estimated_calls=0,
        )
        assert fp.frame_id == "secrets"
        assert fp.is_llm_powered is False

    def test_llm_powered_frame(self):
        fp = FramePlan("semantic", "Semantic", "LLM analysis", True, 1)
        assert fp.is_llm_powered is True
        assert fp.estimated_calls == 1


# ---------------------------------------------------------------------------
# ScanPlanner.plan() — happy paths
# ---------------------------------------------------------------------------


class TestScanPlannerPlan:
    @pytest.fixture
    def planner(self) -> ScanPlanner:
        return ScanPlanner()

    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_plan_with_none_config_uses_standard_level(self, tmp_path, planner):
        discovery_mock = _make_discovery_result(analyzable=5, total=8)
        with patch(
            "warden.analysis.application.discovery.discoverer.FileDiscoverer",
            return_value=MagicMock(discover_async=AsyncMock(return_value=discovery_mock)),
        ):
            plan = self._run(planner.plan(project_root=tmp_path, config=None))

        assert plan.analysis_level == "standard"

    def test_plan_propagates_file_count(self, tmp_path, planner):
        discovery_mock = _make_discovery_result(analyzable=42, total=60)
        with patch(
            "warden.analysis.application.discovery.discoverer.FileDiscoverer",
            return_value=MagicMock(discover_async=AsyncMock(return_value=discovery_mock)),
        ):
            plan = self._run(planner.plan(project_root=tmp_path, config=None))

        assert plan.file_count == 42

    def test_plan_propagates_skipped_count(self, tmp_path, planner):
        discovery_mock = _make_discovery_result(analyzable=42, total=60)
        with patch(
            "warden.analysis.application.discovery.discoverer.FileDiscoverer",
            return_value=MagicMock(discover_async=AsyncMock(return_value=discovery_mock)),
        ):
            plan = self._run(planner.plan(project_root=tmp_path, config=None))

        assert plan.skipped_count == 18  # 60 - 42

    def test_plan_stores_project_root(self, tmp_path, planner):
        discovery_mock = _make_discovery_result(5, 5)
        with patch(
            "warden.analysis.application.discovery.discoverer.FileDiscoverer",
            return_value=MagicMock(discover_async=AsyncMock(return_value=discovery_mock)),
        ):
            plan = self._run(planner.plan(project_root=tmp_path, config=None))

        assert str(tmp_path) in plan.project_root

    def test_plan_with_basic_level_has_zero_llm_calls(self, tmp_path, planner):
        discovery_mock = _make_discovery_result(10, 15)
        with patch(
            "warden.analysis.application.discovery.discoverer.FileDiscoverer",
            return_value=MagicMock(discover_async=AsyncMock(return_value=discovery_mock)),
        ):
            plan = self._run(planner.plan(project_root=tmp_path, config=_Config("basic")))

        # basic level => LLM factor = 0.0
        assert plan.estimated_llm_calls == 0

    def test_plan_with_deep_level_has_more_llm_calls_than_standard(self, tmp_path, planner):
        discovery_mock = _make_discovery_result(10, 10)
        with patch(
            "warden.analysis.application.discovery.discoverer.FileDiscoverer",
            return_value=MagicMock(discover_async=AsyncMock(return_value=discovery_mock)),
        ):
            plan_standard = self._run(
                planner.plan(project_root=tmp_path, config=_Config("standard"))
            )
            plan_deep = self._run(
                planner.plan(project_root=tmp_path, config=_Config("deep"))
            )

        # deep should estimate at least as many (or more) LLM calls
        assert plan_deep.estimated_llm_calls >= plan_standard.estimated_llm_calls

    def test_plan_reasoning_is_non_empty(self, tmp_path, planner):
        discovery_mock = _make_discovery_result(5, 7)
        with patch(
            "warden.analysis.application.discovery.discoverer.FileDiscoverer",
            return_value=MagicMock(discover_async=AsyncMock(return_value=discovery_mock)),
        ):
            plan = self._run(planner.plan(project_root=tmp_path, config=None))

        assert plan.reasoning, "reasoning must not be empty"

    def test_plan_frames_non_empty(self, tmp_path, planner):
        discovery_mock = _make_discovery_result(5, 5)
        with patch(
            "warden.analysis.application.discovery.discoverer.FileDiscoverer",
            return_value=MagicMock(discover_async=AsyncMock(return_value=discovery_mock)),
        ):
            # Patch registry so it fails → falls back to static frames
            with patch(
                "warden.pipeline.application.scan_planner.ScanPlanner._frames_from_registry",
                side_effect=ImportError("no registry"),
            ):
                plan = self._run(planner.plan(project_root=tmp_path, config=_Config("standard")))

        assert len(plan.frames) > 0

    def test_plan_basic_level_has_no_llm_frames_in_static_fallback(self, tmp_path, planner):
        discovery_mock = _make_discovery_result(5, 5)
        with patch(
            "warden.analysis.application.discovery.discoverer.FileDiscoverer",
            return_value=MagicMock(discover_async=AsyncMock(return_value=discovery_mock)),
        ):
            with patch(
                "warden.pipeline.application.scan_planner.ScanPlanner._frames_from_registry",
                side_effect=ImportError("no registry"),
            ):
                plan = self._run(planner.plan(project_root=tmp_path, config=_Config("basic")))

        llm_frames = [f for f in plan.frames if f.is_llm_powered]
        assert llm_frames == [], "basic level must not include LLM-powered frames"


# ---------------------------------------------------------------------------
# Fallback file count
# ---------------------------------------------------------------------------


class TestFallbackFileCount:
    def test_fallback_counts_code_files(self, tmp_path):
        # Create some code and non-code files
        (tmp_path / "main.py").write_text("print('hello')")
        (tmp_path / "app.js").write_text("console.log('hi')")
        (tmp_path / "README.md").write_text("# readme")  # not a code file
        (tmp_path / "image.png").write_bytes(b"\x89PNG")  # binary/non-code

        planner = ScanPlanner()
        code_count, skipped = planner._fallback_file_count(tmp_path)

        assert code_count >= 2  # py and js
        assert isinstance(skipped, int)

    def test_fallback_skips_hidden_dirs(self, tmp_path):
        hidden_dir = tmp_path / ".git"
        hidden_dir.mkdir()
        (hidden_dir / "config").write_text("[core]")

        (tmp_path / "real.py").write_text("x = 1")

        planner = ScanPlanner()
        code_count, skipped = planner._fallback_file_count(tmp_path)

        assert code_count == 1
        assert skipped >= 1  # the .git/config file is skipped


# ---------------------------------------------------------------------------
# _build_reasoning
# ---------------------------------------------------------------------------


class TestBuildReasoning:
    def test_reasoning_mentions_level(self):
        planner = ScanPlanner()
        frames = [FramePlan("s", "S", "r", False, 0), FramePlan("l", "L", "r", True, 1)]
        text = planner._build_reasoning("deep", 10, frames, 5)
        assert "deep" in text.lower() or "Deep" in text

    def test_reasoning_mentions_file_count(self):
        planner = ScanPlanner()
        frames = [FramePlan("s", "S", "r", False, 0)]
        text = planner._build_reasoning("standard", 42, frames, 3)
        assert "42" in text

    def test_reasoning_mentions_skipped_count(self):
        planner = ScanPlanner()
        frames = [FramePlan("s", "S", "r", False, 0)]
        text = planner._build_reasoning("basic", 10, frames, 99)
        assert "99" in text
