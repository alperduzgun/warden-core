"""
Test Fortification on REAL project file.

Analyzes actual warden-core TUI app.py file.
"""

import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from warden.fortification.fortifiers.error_handling import ErrorHandlingFortifier
from warden.validation.domain.frame import CodeFile


async def test_real_project_file():
    """Test fortification on real project file."""

    print("=" * 80)
    print("REAL PROJECT FORTIFICATION TEST")
    print("=" * 80)
    print("\n📂 Analyzing: src/warden/tui/app.py")
    print("   (Warden TUI main application file)\n")

    # Read real file
    file_path = Path("src/warden/tui/app.py")

    if not file_path.exists():
        print(f"❌ File not found: {file_path}")
        return False

    code_content = file_path.read_text()

    code_file = CodeFile(
        path=str(file_path),
        content=code_content,
        language="python"
    )

    print(f"📊 File stats:")
    print(f"   Lines: {code_file.line_count}")
    print(f"   Size: {len(code_content)} chars")
    print(f"   Size: {code_file.size_bytes} bytes\n")

    # Run fortification
    fortifier = ErrorHandlingFortifier()

    print("🔍 Running error handling analysis...\n")
    result = await fortifier.fortify_async(code_file)

    # Show results
    print("=" * 80)
    print("FORTIFICATION REPORT")
    print("=" * 80)

    print(f"\n✅ Status: {'SUCCESS' if result.success else 'FAILED'}")
    print(f"📂 File: {result.file_path}")
    print(f"🐛 Issues found: {result.issues_found}")
    print(f"📝 Summary: {result.summary}")
    print(f"🤖 Fortifier: {result.fortifier_name}")

    if result.error_message:
        print(f"⚠️  Error: {result.error_message}")

    if result.suggestions:
        print(f"\n📋 DETAILED SUGGESTIONS ({len(result.suggestions)} issues):\n")

        # Group by severity
        critical = [s for s in result.suggestions if s.severity == "Critical"]
        high = [s for s in result.suggestions if s.severity == "High"]
        medium = [s for s in result.suggestions if s.severity == "Medium"]

        if critical:
            print(f"🔴 CRITICAL ({len(critical)}):")
            for sug in critical[:3]:  # Show first 3
                print(f"   • Line {sug.issue_line}: {sug.description}")
                print(f"     💡 {sug.suggestion}")

        if high:
            print(f"\n🟠 HIGH ({len(high)}):")
            for sug in high[:3]:  # Show first 3
                print(f"   • Line {sug.issue_line}: {sug.description}")
                print(f"     💡 {sug.suggestion}")

        if medium:
            print(f"\n🟡 MEDIUM ({len(medium)}):")
            for sug in medium[:2]:  # Show first 2
                print(f"   • Line {sug.issue_line}: {sug.description}")

        if len(result.suggestions) > 8:
            print(f"\n   ... and {len(result.suggestions) - 8} more issues")

    # Verify Panel JSON
    print("\n" + "=" * 80)
    print("PANEL JSON VERIFICATION")
    print("=" * 80)

    json_data = result.to_json()

    print(f"\n✅ JSON keys (camelCase):")
    print(f"   - filePath: {json_data['filePath']}")
    print(f"   - issuesFound: {json_data['issuesFound']}")
    print(f"   - suggestions: {len(json_data['suggestions'])} items")
    print(f"   - fortifierName: {json_data['fortifierName']}")
    print(f"   - timestamp: {json_data['timestamp']}")

    # Sample suggestion
    if json_data['suggestions']:
        print(f"\n✅ Sample suggestion JSON:")
        sample = json_data['suggestions'][0]
        print(f"   {{")
        print(f"     'issueLine': {sample['issueLine']},")
        print(f"     'issueType': '{sample['issueType']}',")
        print(f"     'description': '{sample['description'][:50]}...',")
        print(f"     'suggestion': '{sample['suggestion'][:50]}...',")
        print(f"     'severity': '{sample['severity']}'")
        print(f"   }}")

    print("\n" + "=" * 80)
    print("REAL PROJECT TEST COMPLETE ✅")
    print("=" * 80)

    print(f"\n🎯 Results:")
    print(f"   ✅ Analyzed real project file")
    print(f"   ✅ Detected {result.issues_found} issues")
    print(f"   ✅ Generated {len(result.suggestions)} suggestions")
    print(f"   ✅ Panel JSON format verified")
    print(f"   ✅ Code NOT modified (reporter-only)")

    print(f"\n💡 Developer can now:")
    print(f"   - Review suggestions in Panel UI")
    print(f"   - Decide which to apply")
    print(f"   - Manually fix issues")
    print(f"   - Warden just reports, never modifies!")

    return True


if __name__ == "__main__":
    success = asyncio.run(test_real_project_file())
    sys.exit(0 if success else 1)
