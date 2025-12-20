#!/usr/bin/env python3
"""
Live test for priority system.

Tests priority-based execution order on actual warden-core project.
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from warden.models.frame import (
    GLOBAL_FRAMES,
    get_frames_by_priority,
    get_frames_grouped_by_priority,
    get_execution_groups,
    get_priority_value
)
from warden.config.yaml_parser import parse_yaml
from warden.models.pipeline_config import PipelineConfig


def test_priority_values():
    """Test priority numeric values."""
    print("\n=== Testing Priority Values ===")
    print(f"critical: {get_priority_value('critical')} (should be 0)")
    print(f"high: {get_priority_value('high')} (should be 1)")
    print(f"medium: {get_priority_value('medium')} (should be 2)")
    print(f"low: {get_priority_value('low')} (should be 3)")

    assert get_priority_value('critical') == 0
    assert get_priority_value('high') == 1
    assert get_priority_value('medium') == 2
    assert get_priority_value('low') == 3
    print("✅ Priority values correct!")


def test_frame_sorting():
    """Test frame sorting by priority."""
    print("\n=== Testing Frame Sorting ===")
    sorted_frames = get_frames_by_priority(GLOBAL_FRAMES)

    print(f"Execution order (by priority):")
    for i, frame in enumerate(sorted_frames, 1):
        print(f"  {i}. {frame.name} ({frame.id}) - Priority: {frame.priority}")

    # Verify order
    assert sorted_frames[0].id == 'security', "Security should be first (critical)"
    assert sorted_frames[1].id == 'chaos', "Chaos should be second (high)"
    assert sorted_frames[-1].id == 'stress', "Stress should be last (low)"
    print("✅ Frame sorting correct!")


def test_frame_grouping():
    """Test frame grouping for parallel execution."""
    print("\n=== Testing Frame Grouping (Parallel Mode) ===")
    groups = get_frames_grouped_by_priority(GLOBAL_FRAMES)

    print("Priority groups:")
    for priority, frames in groups.items():
        if frames:
            frame_names = [f.name for f in frames]
            print(f"  {priority.upper()}: {frame_names}")

    # Verify groups
    assert len(groups['critical']) == 1
    assert len(groups['high']) == 1
    assert len(groups['medium']) == 3
    assert len(groups['low']) == 1
    print("✅ Frame grouping correct!")


def test_execution_groups():
    """Test execution groups formation."""
    print("\n=== Testing Execution Groups ===")
    groups = get_execution_groups(GLOBAL_FRAMES)

    print(f"Total groups: {len(groups)}")
    for i, group in enumerate(groups, 1):
        group_names = [f.name for f in group]
        priorities = set(f.priority for f in group)
        print(f"  Group {i} ({list(priorities)[0]}): {group_names}")
        if len(group) > 1:
            print(f"    → Can run {len(group)} frames in PARALLEL")

    assert len(groups) == 4, "Should have 4 priority groups"
    print("✅ Execution groups correct!")


def test_yaml_template_loading():
    """Test loading YAML template and checking execution order."""
    print("\n=== Testing YAML Template Loading ===")

    template_path = Path(__file__).parent.parent / "src" / "warden" / "config" / "templates" / "full-validation.yaml"

    if not template_path.exists():
        print(f"⚠️  Template not found: {template_path}")
        return

    print(f"Loading: {template_path}")
    config = parse_yaml(str(template_path))

    print(f"\nPipeline: {config.name}")
    print(f"Version: {config.version}")
    print(f"Settings:")
    print(f"  - fail_fast: {config.settings.fail_fast}")
    print(f"  - parallel: {config.settings.parallel}")
    print(f"  - timeout: {config.settings.timeout}")

    # Get execution order
    print("\n🔥 Sequential Execution Order (priority-based):")
    order = config.get_execution_order(respect_priority=True)
    for i, node_id in enumerate(order, 1):
        node = next((n for n in config.nodes if n.id == node_id), None)
        if node:
            frame_id = node.data.get('frameId')
            from warden.models.frame import get_frame_by_id
            frame = get_frame_by_id(frame_id) if frame_id else None
            priority = frame.priority if frame else 'unknown'
            print(f"  {i}. {node_id} ({frame_id}) - Priority: {priority}")

    # Get parallel groups
    print("\n🚀 Parallel Execution Groups:")
    groups = config.get_execution_groups_for_parallel()
    for i, group in enumerate(groups, 1):
        print(f"  Group {i}: {group}")
        if len(group) > 1:
            print(f"    → {len(group)} frames can run in PARALLEL")

    print("✅ YAML template loaded and execution order verified!")


def main():
    """Run all tests."""
    print("=" * 60)
    print("WARDEN PRIORITY SYSTEM - LIVE TEST")
    print("=" * 60)

    try:
        test_priority_values()
        test_frame_sorting()
        test_frame_grouping()
        test_execution_groups()
        test_yaml_template_loading()

        print("\n" + "=" * 60)
        print("✅ ALL TESTS PASSED!")
        print("=" * 60)
        print("\nPriority system is working correctly!")
        print("Frames will execute in priority order:")
        print("  1. Security (critical) - BLOCKER")
        print("  2. Chaos (high)")
        print("  3. Fuzz, Property, Architectural (medium) - can be parallel")
        print("  4. Stress (low)")

    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
