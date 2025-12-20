"""
Enhanced Pipeline Usage Example

Demonstrates how to use the EnhancedPipelineOrchestrator with:
- Automatic file discovery
- Build context loading
- Suppression filtering
- GitChanges and Orphan frames
"""

import asyncio
from pathlib import Path

from warden.pipeline import (
    EnhancedPipelineOrchestrator,
    PipelineConfig,
    ExecutionStrategy,
)
from warden.validation import (
    SecurityFrame,
    GitChangesFrame,
    OrphanFrame,
)


async def example_1_basic_usage():
    """
    Example 1: Basic enhanced pipeline with all features enabled.

    This demonstrates the simplest usage with default settings.
    All phases (discovery, build context, suppression) are enabled by default.
    """
    print("=" * 80)
    print("Example 1: Basic Enhanced Pipeline Usage")
    print("=" * 80)

    # Create frames
    frames = [
        SecurityFrame(),
        GitChangesFrame(),
        OrphanFrame(),
    ]

    # Create orchestrator with default config (all features enabled)
    orchestrator = EnhancedPipelineOrchestrator(frames=frames)

    # Execute on project
    project_path = "/path/to/your/project"
    result = await orchestrator.execute_with_discovery(project_path)

    # Display results
    print(f"\nPipeline Status: {result.status.name}")
    print(f"Total Findings: {result.total_findings}")
    print(f"Files Discovered: {orchestrator.discovery_result.stats.total_files}")
    print(f"Build System: {orchestrator.build_context.build_system.value if orchestrator.build_context else 'None'}")
    print(f"Suppressed: {result.metadata.get('suppressed_count', 0)} findings")


async def example_2_custom_configuration():
    """
    Example 2: Custom pipeline configuration.

    Demonstrates how to customize discovery, build context, and suppression settings.
    """
    print("\n" + "=" * 80)
    print("Example 2: Custom Pipeline Configuration")
    print("=" * 80)

    # Create frames
    frames = [
        SecurityFrame(),
        GitChangesFrame(config={
            "compare_mode": "branch",
            "base_branch": "develop",
        }),
        OrphanFrame(config={
            "ignore_private": True,
            "ignore_test_files": True,
        }),
    ]

    # Custom configuration
    config = PipelineConfig(
        strategy=ExecutionStrategy.PARALLEL,
        fail_fast=False,
        parallel_limit=4,
        timeout=600,

        # Discovery settings
        enable_discovery=True,
        discovery_config={
            "max_depth": 10,
            "use_gitignore": True,
        },

        # Build context settings
        enable_build_context=True,

        # Suppression settings
        enable_suppression=True,
        suppression_config_path=".warden/suppressions.yaml",
    )

    # Create orchestrator
    orchestrator = EnhancedPipelineOrchestrator(frames=frames, config=config)

    # Execute
    project_path = "/path/to/your/project"
    result = await orchestrator.execute_with_discovery(project_path)

    # Display detailed results
    print(f"\nPipeline completed in {result.duration:.2f}s")
    print(f"Strategy: {config.strategy.value}")
    print(f"Total Frames: {result.total_frames}")
    print(f"Frames Passed: {result.frames_passed}")
    print(f"Frames Failed: {result.frames_failed}")

    print("\nFindings by Severity:")
    print(f"  Critical: {result.critical_findings}")
    print(f"  High: {result.high_findings}")
    print(f"  Medium: {result.medium_findings}")
    print(f"  Low: {result.low_findings}")


async def example_3_selective_phases():
    """
    Example 3: Enable/disable specific phases.

    Shows how to selectively enable or disable discovery, build context, and suppression.
    """
    print("\n" + "=" * 80)
    print("Example 3: Selective Phase Enabling")
    print("=" * 80)

    frames = [SecurityFrame()]

    # Only enable discovery and suppression (no build context)
    config = PipelineConfig(
        enable_discovery=True,
        enable_build_context=False,  # Skip build context
        enable_suppression=True,
    )

    orchestrator = EnhancedPipelineOrchestrator(frames=frames, config=config)

    project_path = "/path/to/your/project"
    result = await orchestrator.execute_with_discovery(project_path)

    print(f"\nDiscovery enabled: {config.enable_discovery}")
    print(f"Build context enabled: {config.enable_build_context}")
    print(f"Suppression enabled: {config.enable_suppression}")

    print(f"\nDiscovery result: {orchestrator.get_discovery_result() is not None}")
    print(f"Build context: {orchestrator.get_build_context() is not None}")
    print(f"Suppression matcher: {orchestrator.get_suppression_matcher() is not None}")


async def example_4_manual_code_files():
    """
    Example 4: Manual code files (no discovery).

    Demonstrates using the pipeline without automatic discovery.
    """
    print("\n" + "=" * 80)
    print("Example 4: Manual Code Files (No Discovery)")
    print("=" * 80)

    from warden.validation import CodeFile

    frames = [SecurityFrame()]

    # Disable all optional phases
    config = PipelineConfig(
        enable_discovery=False,
        enable_build_context=False,
        enable_suppression=False,
    )

    orchestrator = EnhancedPipelineOrchestrator(frames=frames, config=config)

    # Manually create code files
    code_files = [
        CodeFile(
            path="app.py",
            content=Path("app.py").read_text(),
            language="python",
        ),
        CodeFile(
            path="utils.py",
            content=Path("utils.py").read_text(),
            language="python",
        ),
    ]

    # Execute on manual files
    result = await orchestrator.execute(code_files)

    print(f"\nProcessed {len(code_files)} files manually")
    print(f"Total findings: {result.total_findings}")


async def example_5_accessing_phase_results():
    """
    Example 5: Accessing phase results.

    Shows how to access discovery, build context, and suppression results after execution.
    """
    print("\n" + "=" * 80)
    print("Example 5: Accessing Phase Results")
    print("=" * 80)

    frames = [SecurityFrame(), OrphanFrame()]
    orchestrator = EnhancedPipelineOrchestrator(frames=frames)

    project_path = "/path/to/your/project"
    result = await orchestrator.execute_with_discovery(project_path)

    # Access discovery result
    discovery = orchestrator.get_discovery_result()
    if discovery:
        print("\nDiscovery Results:")
        print(f"  Total files: {discovery.stats.total_files}")
        print(f"  Analyzable files: {discovery.stats.analyzable_files}")
        print(f"  Total size: {discovery.stats.total_size_bytes:,} bytes")
        print(f"  Scan duration: {discovery.stats.scan_duration_seconds:.2f}s")

        # Get files by type
        python_files = discovery.get_files_by_type("python")
        print(f"  Python files: {len(python_files)}")

        # Framework detection
        if discovery.framework_detection.frameworks:
            print(f"\n  Detected frameworks:")
            for fw in discovery.framework_detection.frameworks:
                print(f"    - {fw.name} (confidence: {fw.confidence})")

    # Access build context
    build_ctx = orchestrator.get_build_context()
    if build_ctx:
        print("\nBuild Context:")
        print(f"  Build system: {build_ctx.build_system.value}")
        print(f"  Project: {build_ctx.project_name} v{build_ctx.project_version}")
        print(f"  Dependencies: {len(build_ctx.dependencies)}")

        # Show some dependencies
        if build_ctx.dependencies:
            print("\n  Sample dependencies:")
            for dep in list(build_ctx.dependencies)[:5]:
                print(f"    - {dep.name} {dep.version} ({dep.dependency_type.value})")

    # Access suppression matcher
    suppression = orchestrator.get_suppression_matcher()
    if suppression:
        print("\nSuppression:")
        print(f"  Enabled: {suppression.config.enabled}")
        print(f"  Global rules suppressed: {len(suppression.config.global_suppressed_rules)}")
        print(f"  Suppression entries: {len(suppression.config.entries)}")


async def example_6_ci_cd_usage():
    """
    Example 6: CI/CD pipeline usage.

    Demonstrates optimal configuration for CI/CD environments.
    """
    print("\n" + "=" * 80)
    print("Example 6: CI/CD Pipeline Configuration")
    print("=" * 80)

    # Frames optimized for CI/CD
    frames = [
        SecurityFrame(),  # Always check security
        GitChangesFrame(config={
            "compare_mode": "branch",  # Compare with base branch
            "base_branch": "main",
        }),  # Only check changed lines
    ]

    # CI/CD optimized config
    config = PipelineConfig(
        strategy=ExecutionStrategy.FAIL_FAST,  # Stop on first blocker
        fail_fast=True,
        timeout=300,  # 5 minute timeout

        enable_discovery=True,
        discovery_config={
            "use_gitignore": True,  # Respect gitignore
        },

        enable_build_context=True,  # Useful for dependency checks
        enable_suppression=True,  # Filter known false positives
        suppression_config_path=".warden/suppressions.yaml",
    )

    orchestrator = EnhancedPipelineOrchestrator(frames=frames, config=config)

    project_path = "/path/to/your/project"
    result = await orchestrator.execute_with_discovery(project_path)

    # CI/CD reporting
    print(f"\nCI/CD Results:")
    print(f"Status: {result.status.name}")
    print(f"Duration: {result.duration:.2f}s")
    print(f"Exit code: {0 if result.passed else 1}")

    if not result.passed:
        print("\nBLOCKER ISSUES FOUND:")
        for frame_result in result.frame_results:
            if frame_result.is_blocker and not frame_result.passed:
                print(f"\n  Frame: {frame_result.frame_name}")
                print(f"  Issues: {frame_result.issues_found}")
                for finding in frame_result.findings:
                    print(f"    - [{finding.severity}] {finding.message}")
                    print(f"      Location: {finding.location}")


async def main():
    """Run all examples."""
    # Note: These examples use placeholder paths
    # In real usage, replace with actual project paths

    print("Enhanced Pipeline Usage Examples")
    print("=" * 80)
    print("\nNote: These are demonstration examples.")
    print("Replace '/path/to/your/project' with actual project paths.")
    print("\n")

    try:
        # Uncomment the example you want to run:

        # await example_1_basic_usage()
        # await example_2_custom_configuration()
        # await example_3_selective_phases()
        # await example_4_manual_code_files()
        # await example_5_accessing_phase_results()
        # await example_6_ci_cd_usage()

        print("\nAll examples defined. Uncomment to run specific examples.")

    except Exception as e:
        print(f"\nError running example: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
