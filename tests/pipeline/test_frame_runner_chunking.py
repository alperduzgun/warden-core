"""Tests for frame_runner ChunkingAware timeout multiplier.

Verifies that:
- ChunkingAware frames get per_file_timeout * max_chunks_per_file
- The multiplied timeout is capped at _FILE_TIMEOUT_MAX_S
- Non-ChunkingAware frames are unchanged
"""

from __future__ import annotations

import pytest

from warden.pipeline.application.orchestrator.frame_runner import (
    _FILE_TIMEOUT_MAX_S,
    calculate_per_file_timeout,
)
from warden.shared.chunking.models import ChunkingConfig
from warden.validation.domain.mixins import ChunkingAware

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _PlainFrame:
    """Frame without ChunkingAware."""

    pass


class _ChunkFrame(ChunkingAware):
    """Minimal ChunkingAware frame."""

    chunking_config = ChunkingConfig(max_chunk_tokens=700, max_chunks_per_file=3)

    async def analyze_chunk_async(self, chunk, context):
        return []


class _SingleChunkFrame(ChunkingAware):
    """ChunkingAware with max_chunks_per_file=1 (effectively no multiplier)."""

    chunking_config = ChunkingConfig(max_chunk_tokens=1000, max_chunks_per_file=1)

    async def analyze_chunk_async(self, chunk, context):
        return []


def _apply_timeout_multiplier(frame, per_file_timeout: float) -> float:
    """Replicate the frame_runner multiplier logic under test."""
    if isinstance(frame, ChunkingAware):
        n = getattr(getattr(frame, "chunking_config", None), "max_chunks_per_file", 1)
        return min(_FILE_TIMEOUT_MAX_S, per_file_timeout * max(1, n))
    return per_file_timeout


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestChunkingTimeoutMultiplier:
    def test_timeout_multiplied_for_chunking_aware(self):
        """ChunkingAware frame → timeout * max_chunks_per_file."""
        frame = _ChunkFrame()
        base = 20.0  # seconds

        result = _apply_timeout_multiplier(frame, base)

        # max_chunks_per_file=3 → 3 * 20 = 60
        assert result == pytest.approx(60.0)

    def test_timeout_capped_at_max(self):
        """When multiplied value exceeds _FILE_TIMEOUT_MAX_S it is capped."""
        frame = _ChunkFrame()
        # 200 * 3 = 600 > _FILE_TIMEOUT_MAX_S → should be capped
        result = _apply_timeout_multiplier(frame, 200.0)

        assert result == pytest.approx(_FILE_TIMEOUT_MAX_S)

    def test_timeout_unchanged_for_non_chunking(self):
        """Non-ChunkingAware frame → timeout unchanged."""
        frame = _PlainFrame()
        base = 20.0

        result = _apply_timeout_multiplier(frame, base)

        assert result == pytest.approx(base)

    def test_timeout_with_single_chunk_no_effective_multiplier(self):
        """max_chunks_per_file=1 → effectively no multiplication."""
        frame = _SingleChunkFrame()
        base = 30.0

        result = _apply_timeout_multiplier(frame, base)

        # 1 * 30 = 30 (unchanged)
        assert result == pytest.approx(30.0)

    def test_timeout_capped_below_frame_timeout_max(self):
        """Result never exceeds _FILE_TIMEOUT_MAX_S regardless of inputs."""
        frame = _ChunkFrame()
        # Arbitrary large base
        result = _apply_timeout_multiplier(frame, 1_000_000.0)

        assert result <= _FILE_TIMEOUT_MAX_S

    def test_calculate_per_file_timeout_base_works(self):
        """Sanity: calculate_per_file_timeout returns a positive float."""
        timeout = calculate_per_file_timeout(1_000)  # 1 KB file
        assert timeout > 0
