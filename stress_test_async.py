#!/usr/bin/env python3
"""
Stress Test: Scan 218 Python files via Unix Socket IPC (ASYNC VERSION)
Tests socket connection stability during large scan
"""
import asyncio
import json
import time
from pathlib import Path
from typing import List, Dict, Any


def discover_python_files(directory: str) -> List[Path]:
    """Discover all Python files in directory."""
    base_path = Path(directory)
    python_files = list(base_path.rglob("*.py"))
    return sorted(python_files)


async def send_request(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, method: str, params: Dict[str, Any], request_id: int) -> Dict:
    """Send JSON-RPC request over async socket."""
    request = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
        "id": request_id
    }

    message = json.dumps(request) + "\n"
    writer.write(message.encode('utf-8'))
    await writer.drain()

    # Read response (line-delimited JSON)
    line = await reader.readline()

    if not line:
        raise ConnectionError("Socket connection closed")

    # Parse JSON response
    response_str = line.decode('utf-8').strip()
    return json.loads(response_str)


async def stress_test():
    """Run stress test."""
    print("=" * 80)
    print("🚀 WARDEN STRESS TEST - Socket Connection Stability (ASYNC)")
    print("=" * 80)

    # Discover files
    print("\n📂 Discovering Python files...")
    src_dir = Path(__file__).parent / "src" / "warden"
    files = discover_python_files(str(src_dir))

    print(f"✅ Found {len(files)} Python files\n")

    if len(files) == 0:
        print("❌ No Python files found!")
        return

    # Connect to socket
    socket_path = "/tmp/warden-ipc.sock"
    print(f"🔌 Connecting to IPC server: {socket_path}...")

    try:
        reader, writer = await asyncio.open_unix_connection(socket_path)
        print("✅ Connected to IPC server\n")
    except Exception as e:
        print(f"❌ Failed to connect: {e}")
        print("💡 Start IPC server with: ./warden-ipc start")
        return

    # Test parameters
    total_files = len(files)
    start_time = time.time()

    results = []
    errors = []
    connection_drops = 0
    request_id = 1

    print(f"🔍 Starting scan of {total_files} files...")
    print(f"⏱️  Expected time: ~5-10 minutes")
    print(f"📊 Total operations: {total_files} files × 9 frames = {total_files * 9} updates\n")
    print("-" * 80)

    try:
        # Scan each file
        for i, file_path in enumerate(files, 1):
            progress = f"[{i}/{total_files}]"
            rel_path = file_path.relative_to(Path.cwd())

            try:
                print(f"⏳ {progress} Scanning {rel_path}...", end="", flush=True)

                # Send execute_pipeline request
                response = await send_request(
                    reader,
                    writer,
                    "execute_pipeline",
                    {"file_path": str(file_path)},
                    request_id
                )
                request_id += 1

                # Check for error
                if "error" in response:
                    error_msg = response["error"].get("message", "Unknown error")
                    errors.append({
                        "file": str(rel_path),
                        "error": error_msg
                    })
                    print(f"\r⚠️  {progress} Error: {rel_path} - {error_msg}")
                    continue

                # Get result
                result = response.get("result", {})
                results.append({
                    "file": str(rel_path),
                    "result": result
                })

                issue_count = result.get("total_findings", 0)
                status = "🔴" if issue_count > 0 else "✅"

                print(f"\r{status} {progress} {rel_path} - {issue_count} issues")

            except ConnectionError as e:
                connection_drops += 1
                errors.append({
                    "file": str(rel_path),
                    "error": f"Connection drop: {e}"
                })
                print(f"\r❌ {progress} CONNECTION DROP: {rel_path}")
                break  # Stop on connection drop

            except Exception as e:
                errors.append({
                    "file": str(rel_path),
                    "error": str(e)
                })
                print(f"\r⚠️  {progress} Unexpected error: {rel_path} - {e}")

            # Progress update every 10 files
            if i % 10 == 0:
                elapsed = time.time() - start_time
                avg_time = elapsed / i
                remaining = (total_files - i) * avg_time
                print(f"📊 Progress: {i}/{total_files} ({i*100//total_files}%) | "
                      f"Elapsed: {elapsed:.1f}s | Remaining: ~{remaining:.1f}s")

    finally:
        # Close socket
        writer.close()
        await writer.wait_closed()
        print("\n🔌 Socket closed")

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
        print("❌ Original bug NOT fixed!")
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

    # Top files with most issues
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
    if connection_drops == 0:
        print("✅ STRESS TEST COMPLETE - SOCKET STABLE!")
    else:
        print("❌ STRESS TEST FAILED - CONNECTION DROPS DETECTED")
    print("=" * 80)

    # Save summary
    summary_file = Path(__file__).parent / "stress_test_summary.json"
    with open(summary_file, "w") as f:
        json.dump({
            "total_files": total_files,
            "files_scanned": len(results),
            "total_time": total_time,
            "connection_drops": connection_drops,
            "errors": len(errors),
            "total_issues": total_issues,
            "avg_time_per_file": avg_time_per_file,
            "success": connection_drops == 0,
            "test_date": time.strftime("%Y-%m-%d %H:%M:%S")
        }, f, indent=2)

    print(f"\n📄 Summary saved to: {summary_file}")


if __name__ == "__main__":
    asyncio.run(stress_test())
