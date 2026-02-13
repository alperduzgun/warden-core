"""Tests for PIPELINE execution strategy."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from warden.pipeline.domain.enums import ExecutionStrategy
from warden.pipeline.domain.models import FrameChain


class TestFrameChain:
    def test_basic_creation(self):
        chain = FrameChain(frame="security")
        assert chain.frame == "security"
        assert chain.on_complete == []
        assert chain.skip_if is None
        assert chain.priority == 1

    def test_with_dependencies(self):
        chain = FrameChain(
            frame="fortification",
            on_complete=["cleanup"],
            skip_if="no_findings",
            priority=2
        )
        assert chain.on_complete == ["cleanup"]
        assert chain.skip_if == "no_findings"

    def test_to_json(self):
        chain = FrameChain(frame="security", priority=1)
        j = chain.to_json()
        assert j["frame"] == "security"


class TestPipelineStrategy:
    def test_pipeline_enum_exists(self):
        assert ExecutionStrategy.PIPELINE.value == "pipeline"

    def test_all_strategies(self):
        strategies = [s.value for s in ExecutionStrategy]
        assert "sequential" in strategies
        assert "parallel" in strategies
        assert "fail_fast" in strategies
        assert "pipeline" in strategies
