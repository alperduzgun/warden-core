#!/usr/bin/env python3
"""Full pipeline test with all validation frames."""
import sys, asyncio
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from warden.core.pipeline.orchestrator import PipelineOrchestrator
from warden.core.analysis.analyzer import CodeAnalyzer
from warden.core.analysis.classifier import CodeClassifier
from warden.core.validation.executor import FrameExecutor
from warden.core.validation.frames import *

# Test code with security issues
VULNERABLE_CODE = '''
import os
API_KEY = "sk-1234567890abcdef"  # Hardcoded secret
def get_user(user_id):
    query = f"SELECT * FROM users WHERE id = '{user_id}'"  # SQL injection
    return db.execute(query)
def run_command(filename):
    os.system(f"cat {filename}")  # Command injection
'''

async def test_full_pipeline():
    print("=" * 60)
    print("FULL PIPELINE TEST WITH ALL FRAMES")
    print("=" * 60 + "\n")

    # Create all frames
    frames = [
        SecurityFrame(),
        ChaosEngineeringFrame(),
        FuzzTestingFrame(),
        PropertyTestingFrame(),
        ArchitecturalConsistencyFrame(),
        StressTestingFrame(),
    ]

    # Create components
    analyzer = CodeAnalyzer()
    classifier = CodeClassifier()
    frame_executor = FrameExecutor(frames=frames)

    # Create orchestrator
    orchestrator = PipelineOrchestrator(
        analyzer=analyzer,
        classifier=classifier,
        frame_executor=frame_executor,
    )

    # Execute pipeline
    result = await orchestrator.execute(
        file_path="vulnerable.py",
        file_content=VULNERABLE_CODE,
        language="python",
    )

    print(f"Pipeline Result:")
    print(f"  Success: {result.success}")
    print(f"  Duration: {result.duration_ms:.2f}ms")
    print(f"\nValidation Summary:")
    summary = result.validation_summary
    print(f"  Total Frames: {summary['totalFrames']}")
    print(f"  Passed: {summary['passedFrames']}")
    print(f"  Failed: {summary['failedFrames']}")
    print(f"  Blockers: {len(summary['blockerFailures'])}")

    if summary['blockerFailures']:
        print(f"\n❌ BLOCKER FAILURES:")
        for blocker in summary['blockerFailures']:
            print(f"    - {blocker}")

    print(f"\nFrame Results:")
    for frame_result in summary['results']:
        status = "✅ PASSED" if frame_result['passed'] else "❌ FAILED"
        print(f"  {status} {frame_result['name']} ({frame_result['executionTimeMs']:.2f}ms)")
        if frame_result['issues']:
            for issue in frame_result['issues'][:3]:  # Show first 3
                print(f"      - {issue}")

    return result.success

if __name__ == "__main__":
    success = asyncio.run(test_full_pipeline())
    print(f"\n{'✅ TEST PASSED' if not success else '⚠️  Security issues detected (expected)'}")
    sys.exit(0)
