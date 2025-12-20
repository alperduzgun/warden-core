#!/usr/bin/env python3
"""
Integration test for core execution engine.

Tests the full pipeline:
- PipelineOrchestrator
- FrameExecutor
- CodeAnalyzer
- CodeClassifier

Without actual validation frames (those will be Phase 2).
"""
import sys
import asyncio
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from warden.core.pipeline.orchestrator import PipelineOrchestrator
from warden.core.analysis.analyzer import CodeAnalyzer
from warden.core.analysis.classifier import CodeClassifier
from warden.core.validation.executor import FrameExecutor


# Sample Python code for testing
SAMPLE_CODE = '''
import asyncio
import httpx

async def fetch_user_data(user_id: str) -> dict:
    """Fetch user data from API."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"https://api.example.com/users/{user_id}")
            return response.json()
    except Exception as e:
        print(f"Error: {e}")  # Code smell: using print
        return {}

def process_input(data):  # Missing type hints
    # TODO: Add validation
    return data.strip()
'''


async def test_analyzer():
    """Test CodeAnalyzer."""
    print("=" * 60)
    print("TEST 1: CodeAnalyzer")
    print("=" * 60)

    analyzer = CodeAnalyzer()
    result = await analyzer.analyze(
        file_path="test.py",
        file_content=SAMPLE_CODE,
        language="python",
    )

    print(f"\n✅ Analysis completed:")
    print(f"   Score: {result['score']}/10")
    print(f"   Issues: {len(result['issues'])}")
    print(f"   Metrics: {result['metrics']}")

    # Assertions
    assert result['score'] > 0, "Score should be > 0"
    assert 'metrics' in result, "Should have metrics"
    assert 'issues' in result, "Should have issues"

    print("\n✓ CodeAnalyzer test PASSED\n")
    return result


async def test_classifier():
    """Test CodeClassifier."""
    print("=" * 60)
    print("TEST 2: CodeClassifier")
    print("=" * 60)

    classifier = CodeClassifier()
    result = await classifier.classify(
        file_path="test.py",
        file_content=SAMPLE_CODE,
        language="python",
    )

    print(f"\n✅ Classification completed:")
    print(f"   Characteristics:")
    for key, value in result['characteristics'].items():
        print(f"      - {key}: {value}")
    print(f"   Recommended frames: {result['recommendedFrames']}")

    # Assertions
    assert result['characteristics']['hasAsync'] == True, "Should detect async"
    assert result['characteristics']['hasExternalCalls'] == True, "Should detect httpx"
    assert 'security' in result['recommendedFrames'], "Should recommend security"
    assert 'chaos' in result['recommendedFrames'], "Should recommend chaos (async + http)"

    print("\n✓ CodeClassifier test PASSED\n")
    return result


async def test_frame_executor():
    """Test FrameExecutor (without actual frames)."""
    print("=" * 60)
    print("TEST 3: FrameExecutor")
    print("=" * 60)

    executor = FrameExecutor(frames=[])  # No frames registered

    result = await executor.execute(
        file_path="test.py",
        file_content=SAMPLE_CODE,
        language="python",
        recommended_frames=["security", "chaos"],
        characteristics={"hasAsync": True},
        correlation_id="test-001",
        parallel=True,
    )

    print(f"\n✅ Frame execution completed:")
    print(f"   Total frames: {result['totalFrames']}")
    print(f"   Passed frames: {result['passedFrames']}")
    print(f"   Failed frames: {result['failedFrames']}")
    print(f"   Blocker failures: {len(result['blockerFailures'])}")

    # Assertions
    assert result['totalFrames'] == 0, "Should have 0 frames (none registered)"
    assert result['blockerFailures'] == [], "Should have no blocker failures"

    print("\n✓ FrameExecutor test PASSED\n")
    return result


async def test_pipeline_orchestrator():
    """Test full PipelineOrchestrator."""
    print("=" * 60)
    print("TEST 4: PipelineOrchestrator (Full Pipeline)")
    print("=" * 60)

    # Create components
    analyzer = CodeAnalyzer()
    classifier = CodeClassifier()
    frame_executor = FrameExecutor(frames=[])  # No frames yet

    # Create orchestrator
    orchestrator = PipelineOrchestrator(
        analyzer=analyzer,
        classifier=classifier,
        frame_executor=frame_executor,
        fortifier=None,  # Not implemented yet
        cleaner=None,    # Not implemented yet
    )

    # Execute pipeline
    result = await orchestrator.execute(
        file_path="test.py",
        file_content=SAMPLE_CODE,
        language="python",
        enable_fortification=False,
        enable_cleaning=False,
        fail_fast=True,
    )

    print(f"\n✅ Pipeline execution completed:")
    print(f"   Success: {result.success}")
    print(f"   Correlation ID: {result.correlation_id}")
    print(f"   Duration: {result.duration_ms:.2f}ms")
    print(f"   Stages completed: {result.stage_count}")
    print(f"   Message: {result.message}")

    # Check stage results
    if result.analysis_result:
        print(f"\n   Analysis:")
        print(f"      Score: {result.analysis_result.get('score')}")
        print(f"      Issues: {len(result.analysis_result.get('issues', []))}")

    if result.classification_result:
        print(f"\n   Classification:")
        print(f"      Recommended: {result.classification_result.get('recommendedFrames')}")

    if result.validation_summary:
        print(f"\n   Validation:")
        print(f"      Total frames: {result.validation_summary.get('totalFrames')}")

    # Assertions
    assert result.success == True, "Pipeline should succeed"
    assert result.analysis_result is not None, "Should have analysis result"
    assert result.classification_result is not None, "Should have classification result"
    assert result.validation_summary is not None, "Should have validation summary"
    assert result.stage_count >= 3, "Should complete at least 3 stages"

    print("\n✓ PipelineOrchestrator test PASSED\n")
    return result


async def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("WARDEN CORE ENGINE - INTEGRATION TESTS")
    print("=" * 60 + "\n")

    try:
        # Run tests
        await test_analyzer()
        await test_classifier()
        await test_frame_executor()
        await test_pipeline_orchestrator()

        print("=" * 60)
        print("✅ ALL TESTS PASSED!")
        print("=" * 60)
        print("\nCore execution engine is working! 🚀")
        print("\nNext steps:")
        print("  1. Implement validation frames (Phase 2)")
        print("  2. Add LLM integration (analyzer + classifier)")
        print("  3. Add resilience patterns (retry, timeout)")
        print("  4. Implement fortification & cleaning\n")

        return 0

    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}\n")
        return 1
    except Exception as e:
        print(f"\n❌ ERROR: {e}\n")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
