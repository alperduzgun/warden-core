"""
Example: Using the Warden IPC Bridge

This script demonstrates how to use the Warden IPC bridge for
communication between Python backend and external clients.
"""

import asyncio
import json
from pathlib import Path

from warden.cli_bridge.server import IPCServer
from warden.cli_bridge.bridge import WardenBridge
from warden.cli_bridge.protocol import IPCRequest, IPCResponse


async def example_simple_echo():
    """Example 1: Simple ping/pong"""
    print("\n=== Example 1: Simple Echo Test ===")

    bridge = WardenBridge()
    server = IPCServer(bridge=bridge, transport="stdio")

    # Simulate a ping request
    request = IPCRequest(method="ping", id=1)
    response = await server._handle_request(request.to_json())

    print(f"Request:  {request.to_json()}")
    print(f"Response: {response.to_json()}")


async def example_execute_pipeline():
    """Example 2: Execute validation pipeline"""
    print("\n=== Example 2: Execute Pipeline ===")

    # Create a test file
    test_file = Path("/tmp/test_example.py")
    test_file.write_text("""
def hello_world():
    print("Hello, World!")
    x = 1 / 0  # Division by zero - should trigger validation
    """)

    bridge = WardenBridge()
    server = IPCServer(bridge=bridge, transport="stdio")

    # Execute pipeline
    request = IPCRequest(
        method="execute_pipeline",
        params={"file_path": str(test_file)},
        id=2,
    )

    print(f"Validating: {test_file}")
    response = await server._handle_request(request.to_json())

    if response.error:
        print(f"Error: {response.error.message}")
    else:
        result = response.result
        print(f"Pipeline Status: {result['status']}")
        print(f"Total Frames: {result['total_frames']}")
        print(f"Frames Passed: {result['frames_passed']}")
        print(f"Frames Failed: {result['frames_failed']}")
        print(f"Total Findings: {result['total_findings']}")

    # Cleanup
    test_file.unlink(missing_ok=True)


async def example_get_config():
    """Example 3: Get Warden configuration"""
    print("\n=== Example 3: Get Configuration ===")

    bridge = WardenBridge()
    server = IPCServer(bridge=bridge, transport="stdio")

    request = IPCRequest(method="get_config", id=3)
    response = await server._handle_request(request.to_json())

    if response.error:
        print(f"Error: {response.error.message}")
    else:
        config = response.result
        print(f"Version: {config['version']}")
        print(f"Default Provider: {config['default_provider']}")
        print(f"Available Providers: {len(config['llm_providers'])}")
        print(f"Total Frames: {config['total_frames']}")

        if config['llm_providers']:
            print("\nLLM Providers:")
            for provider in config['llm_providers']:
                print(f"  - {provider['name']}: {provider['model']}")


async def example_get_frames():
    """Example 4: Get available validation frames"""
    print("\n=== Example 4: Get Available Frames ===")

    bridge = WardenBridge()
    server = IPCServer(bridge=bridge, transport="stdio")

    request = IPCRequest(method="get_available_frames", id=4)
    response = await server._handle_request(request.to_json())

    if response.error:
        print(f"Error: {response.error.message}")
    else:
        frames = response.result
        print(f"Total Frames Available: {len(frames)}")

        if frames:
            print("\nFrames:")
            for frame in frames[:5]:  # Show first 5
                print(f"  - {frame['name']} ({frame['priority']})")
                print(f"    ID: {frame['id']}")
                print(f"    Blocker: {frame['is_blocker']}")


async def example_analyze_with_llm():
    """Example 5: Analyze code with LLM"""
    print("\n=== Example 5: Analyze with LLM ===")

    bridge = WardenBridge()
    server = IPCServer(bridge=bridge, transport="stdio")

    # Note: This will fail if no LLM provider is configured
    request = IPCRequest(
        method="analyze_with_llm",
        params={
            "prompt": "Explain what a validation pipeline is",
            "stream": False,
        },
        id=5,
    )

    print("Analyzing with LLM...")
    response = await server._handle_request(request.to_json())

    if response.error:
        print(f"Error: {response.error.message}")
        if response.error.code == -32004:  # LLM_ERROR
            print("Note: This requires LLM provider to be configured in .env")
    else:
        result = response.result
        print(f"Chunks received: {len(result.get('chunks', []))}")


async def example_error_handling():
    """Example 6: Error handling"""
    print("\n=== Example 6: Error Handling ===")

    bridge = WardenBridge()
    server = IPCServer(bridge=bridge, transport="stdio")

    # Test 1: Method not found
    print("\nTest 1: Method not found")
    request = IPCRequest(method="nonexistent_method", id=6)
    response = await server._handle_request(request.to_json())
    print(f"Error Code: {response.error.code}")
    print(f"Error Message: {response.error.message}")

    # Test 2: File not found
    print("\nTest 2: File not found")
    request = IPCRequest(
        method="execute_pipeline",
        params={"file_path": "/nonexistent/file.py"},
        id=7,
    )
    response = await server._handle_request(request.to_json())
    print(f"Error Code: {response.error.code}")
    print(f"Error Message: {response.error.message}")

    # Test 3: Invalid JSON-RPC version
    print("\nTest 3: Invalid request")
    request = IPCRequest(jsonrpc="1.0", method="ping", id=8)
    response = await server._handle_request(request.to_json())
    print(f"Error Code: {response.error.code}")
    print(f"Error Message: {response.error.message}")


async def main():
    """Run all examples"""
    print("=" * 60)
    print("Warden IPC Bridge Examples")
    print("=" * 60)

    try:
        await example_simple_echo()
        await example_execute_pipeline()
        await example_get_config()
        await example_get_frames()
        await example_analyze_with_llm()
        await example_error_handling()

    except Exception as e:
        print(f"\nUnexpected error: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 60)
    print("Examples completed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
