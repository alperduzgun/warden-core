#!/usr/bin/env python3
"""
Test ProjectArchitectureFrame on warden-core.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from warden.shared.domain.project_context import ProjectContext
from warden.validation.frames.project_architecture.project_architecture_frame import (
    ProjectArchitectureFrame
)


async def main():
    print("=" * 80)
    print("🔍 WARDEN PROJECT ARCHITECTURE ANALYSIS (DOGFOODING)")
    print("=" * 80)
    print()

    # Scan warden-core itself
    project_root = Path(__file__).parent / "src"
    print(f"📁 Analyzing: {project_root}")
    print()

    # Create project context
    print("⏳ Scanning project structure...")
    ctx = ProjectContext.from_project_root(project_root)

    stats = ctx.get_module_statistics()
    print(f"✅ Scan complete!")
    print(f"   Total modules: {stats['total_modules']}")
    print(f"   Total files: {stats['total_files']}")
    print(f"   Empty modules: {stats['empty_modules']}")
    print(f"   Total lines: {stats['total_lines']:,}")
    print()

    # Create and run frame
    print("⚡ Running ProjectArchitectureFrame...")
    frame = ProjectArchitectureFrame(config={
        "detect_empty_modules": True,
        "detect_duplicates": True,
        "detect_pattern_mixing": True,
        "detect_unnecessary_layers": True,
    })

    result = await frame.execute(ctx)

    print(f"✅ Analysis complete! ({result.duration:.2f}s)")
    print()

    # Results
    print("=" * 80)
    print("📊 RESULTS")
    print("=" * 80)
    print(f"Status: {result.status.upper()}")
    print(f"Total Issues: {result.issues_found}")
    print()

    # Metadata
    if result.metadata:
        print("📈 Breakdown:")
        print(f"   Empty modules: {result.metadata.get('empty_modules', 0)}")
        print(f"   Duplicate modules: {result.metadata.get('duplicate_modules', 0)}")
        print(f"   Architectural issues: {result.metadata.get('architectural_issues', 0)}")
        print(f"   Unnecessary layers: {result.metadata.get('unnecessary_layers', 0)}")
        print()

    # Show findings grouped by severity
    if result.findings:
        by_severity = {}
        for f in result.findings:
            by_severity.setdefault(f.severity, []).append(f)

        for sev in ["high", "medium", "low"]:
            if sev in by_severity:
                findings = by_severity[sev]
                print(f"\n{sev.upper()} SEVERITY ({len(findings)} issues)")
                print("-" * 80)

                for i, f in enumerate(findings[:10], 1):  # Show first 10
                    print(f"\n[{i}] {f.message}")
                    loc = f.location
                    if len(loc) > 100:
                        loc = loc[:100] + "..."
                    print(f"    📍 {loc}")

                if len(findings) > 10:
                    print(f"\n    ... and {len(findings) - 10} more")
    else:
        print("✅ No architectural issues found!")

    print("\n" + "=" * 80)
    print("🎯 ANALYSIS COMPLETE")
    print("=" * 80)

    return result


if __name__ == "__main__":
    try:
        result = asyncio.run(main())
        sys.exit(0 if result.status == "passed" else 1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)
