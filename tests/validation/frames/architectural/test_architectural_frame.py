"""
Tests for ArchitecturalFrame.

Note: The architectural frame directory currently has no implementation,
only an empty rules directory. These tests verify the module structure
and will be expanded when the frame is implemented.
"""

import pytest


def test_architectural_module_imports():
    """Test architectural frame module can be imported."""
    try:
        # Try importing the module
        import warden.validation.frames.architectural
        assert warden.validation.frames.architectural is not None
    except ImportError as e:
        pytest.skip(f"Architectural frame module not available: {e}")


def test_architectural_rules_directory_exists():
    """Test architectural frame has rules directory."""
    import os
    from pathlib import Path

    # Find the architectural frame directory
    frame_path = Path(__file__).parent.parent.parent.parent.parent / "src" / "warden" / "validation" / "frames" / "architectural"

    assert frame_path.exists(), "Architectural frame directory should exist"
    assert frame_path.is_dir(), "Architectural frame path should be a directory"

    # Check for rules directory
    rules_path = frame_path / "rules"
    assert rules_path.exists(), "Rules directory should exist"
    assert rules_path.is_dir(), "Rules path should be a directory"


def test_architectural_frame_not_in_registry():
    """Test architectural frame is not yet in registry (no implementation)."""
    from warden.validation.infrastructure.frame_registry import FrameRegistry

    registry = FrameRegistry()
    registry.discover_all()

    # Should not find architectural frame since it's not implemented
    frame_class = registry.get_frame_by_id("architectural")
    assert frame_class is None, "Architectural frame should not be in registry yet (no implementation)"


@pytest.mark.skip(reason="ArchitecturalFrame not yet implemented")
@pytest.mark.asyncio
async def test_architectural_frame_placeholder():
    """Placeholder test for when ArchitecturalFrame is implemented.

    When implemented, this frame should detect:
    - Wrong layer imports (e.g., domain importing infrastructure)
    - Circular dependencies
    - Architecture violations
    - Layered architecture compliance
    """
    # This test will be expanded when frame is implemented
    pytest.skip("ArchitecturalFrame not yet implemented")
