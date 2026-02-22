"""
Tests for ArchitectureFrame registry integration.

These tests verify the ArchitectureFrame (in the 'architecture' directory)
is properly discovered and registered.
"""

import pytest


def test_architecture_module_imports():
    """Test architecture frame module can be imported."""
    from warden.validation.frames.architecture import ArchitectureFrame

    assert ArchitectureFrame is not None


def test_architecture_directory_exists():
    """Test architecture frame directory exists."""
    from pathlib import Path

    frame_path = (
        Path(__file__).parent.parent.parent.parent.parent
        / "src"
        / "warden"
        / "validation"
        / "frames"
        / "architecture"
    )

    assert frame_path.exists(), "Architecture frame directory should exist"
    assert frame_path.is_dir(), "Architecture frame path should be a directory"


def test_architecture_frame_in_registry():
    """Test architecture frame is discovered by the registry."""
    from warden.validation.infrastructure.frame_registry import FrameRegistry

    registry = FrameRegistry()
    registry.discover_all()

    frame_class = registry.get_frame_by_id("architecture")
    assert frame_class is not None, "ArchitectureFrame should be in registry"


@pytest.mark.asyncio
async def test_architecture_frame_metadata():
    """Test ArchitectureFrame has correct metadata."""
    from warden.validation.frames.architecture import ArchitectureFrame

    frame = ArchitectureFrame()
    assert frame.frame_id == "architecture"
    assert frame.name == "Architecture Analysis"
    assert frame.is_blocker is False
    assert frame.version == "1.0.0"


class TestFindingIdToGapType:
    """Tests for _finding_id_to_gap_type helper."""

    def test_missing_mixin_impl(self):
        from warden.validation.frames.architecture.architecture_frame import (
            _finding_id_to_gap_type,
        )
        assert _finding_id_to_gap_type("architecture-missing-mixin-impl-0") == "missing_mixin_impl"

    def test_orphan_file(self):
        from warden.validation.frames.architecture.architecture_frame import (
            _finding_id_to_gap_type,
        )
        assert _finding_id_to_gap_type("architecture-orphan-file-3") == "orphan_file"

    def test_broken_import(self):
        from warden.validation.frames.architecture.architecture_frame import (
            _finding_id_to_gap_type,
        )
        assert _finding_id_to_gap_type("architecture-broken-import-1") == "broken_import"

    def test_unreachable(self):
        from warden.validation.frames.architecture.architecture_frame import (
            _finding_id_to_gap_type,
        )
        assert _finding_id_to_gap_type("architecture-unreachable-5") == "unreachable"

    def test_circular_dep(self):
        from warden.validation.frames.architecture.architecture_frame import (
            _finding_id_to_gap_type,
        )
        assert _finding_id_to_gap_type("architecture-circular-dep-2") == "circular_dep"
