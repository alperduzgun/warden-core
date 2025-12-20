#!/usr/bin/env python3
"""
Simple priority system test (no dependencies).

Tests priority-based execution without external modules.
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


def main():
    """Run priority tests."""
    print("=" * 60)
    print("WARDEN PRIORITY SYSTEM - SIMPLE TEST")
    print("=" * 60)

    # Test 1: Priority values
    print("\n=== Test 1: Priority Values ===")
    print(f"critical: {get_priority_value('critical')} (expect 0)")
    print(f"high: {get_priority_value('high')} (expect 1)")
    print(f"medium: {get_priority_value('medium')} (expect 2)")
    print(f"low: {get_priority_value('low')} (expect 3)")

    assert get_priority_value('critical') == 0
    assert get_priority_value('high') == 1
    assert get_priority_value('medium') == 2
    assert get_priority_value('low') == 3
    print("✅ PASS")

    # Test 2: Frame sorting
    print("\n=== Test 2: Frame Sorting by Priority ===")
    sorted_frames = get_frames_by_priority(GLOBAL_FRAMES)

    print("Execution order (priority-based):")
    for i, frame in enumerate(sorted_frames, 1):
        blocker = "BLOCKER" if frame.is_blocker else ""
        print(f"  {i}. {frame.name:30s} - {frame.priority:8s} {blocker}")

    # Verify first and last
    assert sorted_frames[0].id == 'security', "Security (critical) should be first"
    assert sorted_frames[0].priority == 'critical'
    assert sorted_frames[1].id == 'chaos', "Chaos (high) should be second"
    assert sorted_frames[-1].id == 'stress', "Stress (low) should be last"
    print("✅ PASS")

    # Test 3: Grouping for parallel execution
    print("\n=== Test 3: Parallel Execution Groups ===")
    groups = get_frames_grouped_by_priority(GLOBAL_FRAMES)

    for priority in ['critical', 'high', 'medium', 'low']:
        frames = groups[priority]
        if frames:
            frame_names = [f.name for f in frames]
            print(f"{priority.upper():8s}: {len(frames)} frame(s)")
            for name in frame_names:
                print(f"           - {name}")

    assert len(groups['critical']) == 1, "1 critical frame (security)"
    assert len(groups['high']) == 1, "1 high frame (chaos)"
    assert len(groups['medium']) == 3, "3 medium frames"
    assert len(groups['low']) == 1, "1 low frame (stress)"
    print("✅ PASS")

    # Test 4: Execution groups
    print("\n=== Test 4: Sequential Execution Groups ===")
    exec_groups = get_execution_groups(GLOBAL_FRAMES)

    print(f"Total groups: {len(exec_groups)}")
    for i, group in enumerate(exec_groups, 1):
        priority = group[0].priority
        group_names = [f.name for f in group]
        parallel_note = f"({len(group)} parallel)" if len(group) > 1 else "(sequential)"
        print(f"\nGroup {i} - {priority.upper()} {parallel_note}:")
        for name in group_names:
            print(f"  - {name}")

    assert len(exec_groups) == 4, "Should have 4 priority groups"
    assert len(exec_groups[0]) == 1, "Critical group has 1 frame"
    assert len(exec_groups[2]) == 3, "Medium group has 3 frames (can be parallel)"
    print("\n✅ PASS")

    # Summary
    print("\n" + "=" * 60)
    print("✅ ALL TESTS PASSED!")
    print("=" * 60)
    print("\n📊 EXECUTION ORDER SUMMARY:")
    print("\n🔹 Sequential Mode (parallel=false):")
    print("   1. Security (critical, blocker)")
    print("   2. Chaos (high)")
    print("   3. Fuzz (medium)")
    print("   4. Property (medium)")
    print("   5. Architectural (medium)")
    print("   6. Stress (low)")

    print("\n🔹 Parallel Mode (parallel=true):")
    print("   Group 1: Security (critical) → runs alone")
    print("   Group 2: Chaos (high) → runs alone")
    print("   Group 3: Fuzz + Property + Architectural → PARALLEL")
    print("   Group 4: Stress (low) → runs alone")

    print("\n✅ Priority system working correctly!")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
