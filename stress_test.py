#!/usr/bin/env python3
"""
Stress Test: Scan 218 Python files via IPC
Tests socket connection stability and streaming performance
"""
import time
import asyncio
from pathlib import Path
from typing import List
import json

# IPC Client import
import sys
sys.path.insert(0, str(Path(__file__).parent / "src"))

from warden.cli_bridge.bridge import IPCClient


async def discover_python_files(directory: str) -> List[Path]:
    """Discover all Python files in directory."""
    base_path = Path(directory)
    python_files = list(base_path.rglob("*.py"))
    return python_files


async def stress_test_scan():
    """Run stress test: scan 218 files."""
    print("=" * 80)
    print("🚀 WARDEN STRESS TEST - 218 Python Files")
    print("=" * 80)

    # Discover files
    print("\n📂 Discovering Python files...")
    src_dir = Path(__file__).parent / "src" / "warden"
    files = await discover_python_files(str(src_dir))

    print(f"✅ Found {len(files)} Python files\n")

    if len(files) == 0:
        print("❌ No Python files found!")
        return

    # Connect to IPC server
    print("🔌 Connecting to IPC server...")
    client = IPCClient(socket_path="/tmp/warden-ipc.sock")

    try:
        await client.connect()
        print("✅ Connected to IPC server\n")
    except Exception as e:
        print(f"❌ Failed to connect: {e}")
        return

    # Test parameters
    total_files = len(files)
    start_time = time.time()

    results = []
    errors = []
    connection_drops = 0

    print(f"🔍 Starting scan of {total_files} files...")
    print(f"⏱️  Expected time: ~5-10 minutes")
    print(f"📊 Total operations: {total_files} files × 9 frames = {total_files * 9} updates\n")
    print("-" * 80)

    # Scan each file
    for i, file_path in enumerate(files, 1):
        progress = f"[{i}/{total_files}]"
        rel_path = file_path.relative_to(Path.cwd())

        try:
            # Execute pipeline (blocking version for simplicity)
            print(f"⏳ {progress} Scanning {rel_path}...", end="", flush=True)

            result = await client.execute_pipeline(str(file_path))

            # Track results
            results.append({
                "file": str(rel_path),
                "result": result
            })

            issue_count = result.get("total_findings", 0)
            status = "🔴" if issue_count > 0 else "✅"

            print(f"\r{status} {progress} {rel_path} - {issue_count} issues")

        except Exception as e:
            error_msg = str(e)
            errors.append({
                "file": str(rel_path),
                "error": error_msg
            })

            if "not connected" in error_msg.lower():
                connection_drops += 1
                print(f"\r❌ {progress} CONNECTION DROP: {rel_path}")
            else:
                print(f"\r⚠️  {progress} Error: {rel_path} - {error_msg}")

        # Progress update every 10 files
        if i % 10 == 0:
            elapsed = time.time() - start_time
            avg_time = elapsed / i
            remaining = (total_files - i) * avg_time
            print(f"📊 Progress: {i}/{total_files} ({i*100//total_files}%) | "
                  f"Elapsed: {elapsed:.1f}s | Remaining: ~{remaining:.1f}s")

    # Final summary
    end_time = time.time()
    total_time = end_time - start_time

    print("\n" + "=" * 80)
    print("📊 STRESS TEST RESULTS")
    print("=" * 80)

    print(f"\n⏱️  Total Time: {total_time:.2f} seconds ({total_time/60:.2f} minutes)")
    print(f"📁 Files Scanned: {len(results)}/{total_files}")
    print(f"❌ Errors: {len(errors)}")
    print(f"🔌 Connection Drops: {connection_drops}")

    if connection_drops > 0:
        print(f"\n⚠️  WARNING: {connection_drops} connection drops detected!")
        print("Original bug NOT fixed!")
    else:
        print(f"\n✅ SUCCESS: No connection drops! Socket is stable!")

    # Calculate issue stats
    total_issues = sum(r["result"].get("total_findings", 0) for r in results)
    critical = sum(r["result"].get("critical_findings", 0) for r in results)
    high = sum(r["result"].get("high_findings", 0) for r in results)
    medium = sum(r["result"].get("medium_findings", 0) for r in results)
    low = sum(r["result"].get("low_findings", 0) for r in results)

    print(f"\n🔍 Total Issues Found: {total_issues}")
    if total_issues > 0:
        print(f"  🔴 Critical: {critical}")
        print(f"  🟠 High: {high}")
        print(f"  🟡 Medium: {medium}")
        print(f"  🟢 Low: {low}")

    # Performance metrics
    avg_time_per_file = total_time / len(results) if results else 0
    print(f"\n⚡ Performance:")
    print(f"  Average time per file: {avg_time_per_file:.2f}s")
    print(f"  Files per minute: {len(results) / (total_time/60):.1f}")

    # Top 10 files with most issues
    if results:
        sorted_results = sorted(results, key=lambda x: x["result"].get("total_findings", 0), reverse=True)
        top_files = sorted_results[:10]

        if top_files[0]["result"].get("total_findings", 0) > 0:
            print(f"\n📋 Top 10 Files with Most Issues:")
            for idx, item in enumerate(top_files, 1):
                count = item["result"].get("total_findings", 0)
                if count > 0:
                    print(f"  {idx}. {item['file']}: {count} issues")

    # Error summary
    if errors:
        print(f"\n❌ Errors ({len(errors)}):")
        for err in errors[:10]:  # Show first 10
            print(f"  - {err['file']}: {err['error']}")
        if len(errors) > 10:
            print(f"  ... and {len(errors) - 10} more errors")

    print("\n" + "=" * 80)
    print("✅ STRESS TEST COMPLETE!")
    print("=" * 80)

    # Save results
    report_file = Path(__file__).parent / "stress_test_report.json"
    with open(report_file, "w") as f:
        json.dump({
            "total_files": total_files,
            "files_scanned": len(results),
            "total_time": total_time,
            "connection_drops": connection_drops,
            "errors": len(errors),
            "total_issues": total_issues,
            "avg_time_per_file": avg_time_per_file,
            "results": results[:50],  # Save first 50 for space
            "error_list": errors
        }, f, indent=2)

    print(f"\n📄 Full report saved to: {report_file}")

    await client.close()


if __name__ == "__main__":
    asyncio.run(stress_test_scan())
