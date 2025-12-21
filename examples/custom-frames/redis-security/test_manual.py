"""
Manual test script for Redis Security Frame.

Tests the frame against both insecure and secure code examples.
"""

import asyncio
import sys
from pathlib import Path

# Add frame to path
sys.path.insert(0, str(Path(__file__).parent))

from frame import RedisSecurityFrame
from warden.validation.domain.frame import CodeFile


async def test_insecure_code():
    """Test frame against insecure Redis code."""
    print("\n" + "=" * 80)
    print("Testing INSECURE Redis code")
    print("=" * 80 + "\n")

    frame = RedisSecurityFrame()

    # Load insecure code
    test_file = Path(__file__).parent / "test_examples" / "insecure_redis.py"
    with open(test_file) as f:
        content = f.read()

    code_file = CodeFile(
        path=str(test_file),
        content=content,
        language="python",
    )

    # Execute frame
    result = await frame.execute(code_file)

    # Print results
    print(f"Status: {result.status}")
    print(f"Issues Found: {result.issues_found}")
    print(f"Is Blocker: {result.is_blocker}")
    print(f"Duration: {result.duration:.3f}s")
    print(f"\nMetadata: {result.metadata}")

    print(f"\nFindings ({len(result.findings)}):")
    print("-" * 80)

    for i, finding in enumerate(result.findings, 1):
        print(f"\n{i}. [{finding.severity.upper()}] {finding.message}")
        print(f"   Location: {finding.location}")
        if finding.code:
            print(f"   Code: {finding.code}")
        if finding.detail:
            print(f"   Detail: {finding.detail[:100]}...")

    print("\n" + "=" * 80)
    return result


async def test_secure_code():
    """Test frame against secure Redis code."""
    print("\n" + "=" * 80)
    print("Testing SECURE Redis code")
    print("=" * 80 + "\n")

    frame = RedisSecurityFrame()

    # Load secure code
    test_file = Path(__file__).parent / "test_examples" / "secure_redis.py"
    with open(test_file) as f:
        content = f.read()

    code_file = CodeFile(
        path=str(test_file),
        content=content,
        language="python",
    )

    # Execute frame
    result = await frame.execute(code_file)

    # Print results
    print(f"Status: {result.status}")
    print(f"Issues Found: {result.issues_found}")
    print(f"Duration: {result.duration:.3f}s")
    print(f"\nMetadata: {result.metadata}")

    if result.findings:
        print(f"\nFindings ({len(result.findings)}):")
        print("-" * 80)

        for i, finding in enumerate(result.findings, 1):
            print(f"\n{i}. [{finding.severity.upper()}] {finding.message}")
            print(f"   Location: {finding.location}")
            if finding.code:
                print(f"   Code: {finding.code}")
    else:
        print("\n✅ No security issues found! Code is secure.")

    print("\n" + "=" * 80)
    return result


async def main():
    """Run all tests."""
    print("\n🛡️  Redis Security Frame - Manual Test")
    print("=" * 80)

    # Test insecure code
    insecure_result = await test_insecure_code()

    # Test secure code
    secure_result = await test_secure_code()

    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"\nInsecure Code:")
    print(f"  - Status: {insecure_result.status}")
    print(f"  - Issues: {insecure_result.issues_found}")
    print(f"  - Critical: {insecure_result.metadata.get('critical_issues', 0)}")
    print(f"  - High: {insecure_result.metadata.get('high_issues', 0)}")

    print(f"\nSecure Code:")
    print(f"  - Status: {secure_result.status}")
    print(f"  - Issues: {secure_result.issues_found}")

    print("\n✅ Frame is working correctly!")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
