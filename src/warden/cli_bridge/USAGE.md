# IPC Bridge Usage Guide

## Quick Start

The IPC bridge now supports **three usage modes** depending on your needs:

### 1. Protocol-Only Mode (No Dependencies)

Use just the protocol classes for JSON-RPC communication:

```python
from warden.cli_bridge import IPCRequest, IPCResponse, IPCError, ErrorCode

# Create request
request = IPCRequest(method="ping", params=None, id=1)
print(request.to_json())
# {"jsonrpc": "2.0", "method": "ping", "id": 1}

# Create success response
response = IPCResponse.create_success(
    result={"status": "ok", "message": "pong"},
    request_id=1
)

# Create error response
error = IPCError(
    code=ErrorCode.FILE_NOT_FOUND,
    message="File not found: /path/to/file",
    data={"path": "/path/to/file"}
)
error_response = IPCResponse.create_error(error_obj=error, request_id=1)
```

### 2. Minimal Bridge Mode (For Testing)

Use the minimal bridge when Warden validation framework is not installed:

```python
from warden.cli_bridge import MinimalWardenBridge
import asyncio

async def test():
    bridge = MinimalWardenBridge()

    # Ping (always works)
    result = await bridge.ping()
    # {'status': 'ok', 'mode': 'minimal', 'timestamp': '...'}

    # Get mock config
    config = await bridge.get_config()
    # Returns mock LLM providers and validation frames

    # Get mock frames
    frames = await bridge.get_available_frames()
    # Returns 3 sample validation frames

    # Execute pipeline with mock data
    result = await bridge.execute_pipeline("/path/to/file.py")
    # Returns realistic mock pipeline results

asyncio.run(test())
```

### 3. Full Bridge Mode (With Warden)

Use the full bridge when Warden validation framework is installed:

```python
from warden.cli_bridge import WardenBridge, WARDEN_BRIDGE_AVAILABLE
import asyncio

async def run():
    # Check if full framework available
    if WARDEN_BRIDGE_AVAILABLE:
        print("Full Warden validation framework available")
    else:
        print("Using minimal bridge (fallback mode)")

    # WardenBridge will automatically use MinimalWardenBridge if needed
    bridge = WardenBridge()

    # These always work
    await bridge.ping()
    await bridge.get_config()
    await bridge.get_available_frames()

    # These require full framework (will raise IPCError if not available)
    try:
        result = await bridge.execute_pipeline("/path/to/file.py")
    except IPCError as e:
        print(f"Feature not available: {e.message}")

asyncio.run(run())
```

## IPC Server

Run an IPC server for CLI communication:

### STDIO Transport (for subprocess)

```python
from warden.cli_bridge import IPCServer
import asyncio

async def main():
    server = IPCServer(transport="stdio")
    await server.start()

asyncio.run(main())
```

### Unix Socket Transport

```python
from warden.cli_bridge import IPCServer
import asyncio

async def main():
    server = IPCServer(
        transport="socket",
        socket_path="/tmp/warden-ipc.sock"
    )
    await server.start()

asyncio.run(main())
```

### Command Line

```bash
# STDIO mode (default)
python -m warden.cli_bridge.server

# Unix socket mode
python -m warden.cli_bridge.server --transport socket --socket-path /tmp/warden.sock
```

## Error Handling

```python
from warden.cli_bridge import IPCError, ErrorCode

# IPCError is now a proper Exception
try:
    raise IPCError(
        code=ErrorCode.FILE_NOT_FOUND,
        message="File not found",
        data={"path": "/missing/file"}
    )
except IPCError as e:
    print(f"Code: {e.code}")
    print(f"Message: {e.message}")
    print(f"Data: {e.data}")
```

## Available Methods

All bridge implementations support:

- `ping()` - Health check (always works)
- `get_config()` - Get Warden configuration
- `get_available_frames()` - List validation frames
- `execute_pipeline(file_path)` - Run validation pipeline
- `analyze_with_llm(prompt, provider, stream)` - LLM analysis (requires full framework)

## Conditional Features

Check feature availability at runtime:

```python
from warden.cli_bridge import WARDEN_BRIDGE_AVAILABLE

if WARDEN_BRIDGE_AVAILABLE:
    # Use full features
    from warden.cli_bridge import WardenBridge
    bridge = WardenBridge()
else:
    # Use minimal features for testing
    from warden.cli_bridge import MinimalWardenBridge
    bridge = MinimalWardenBridge()
```

## Response Format

### Success Response
```json
{
  "jsonrpc": "2.0",
  "result": { /* method result */ },
  "id": 1
}
```

### Error Response
```json
{
  "jsonrpc": "2.0",
  "error": {
    "code": -32001,
    "message": "File not found",
    "data": { /* optional error details */ }
  },
  "id": 1
}
```

## Error Codes

Standard JSON-RPC errors:
- `-32700` - Parse error
- `-32600` - Invalid request
- `-32601` - Method not found
- `-32602` - Invalid params
- `-32603` - Internal error

Warden-specific errors:
- `-32000` - Pipeline execution error
- `-32001` - File not found
- `-32002` - Validation error
- `-32003` - Configuration error
- `-32004` - LLM error
- `-32005` - Timeout error

## Testing

```python
import asyncio
from warden.cli_bridge import MinimalWardenBridge

async def test_bridge():
    bridge = MinimalWardenBridge()

    # Test ping
    assert (await bridge.ping())["status"] == "ok"

    # Test config
    config = await bridge.get_config()
    assert config["mock_mode"] == True
    assert config["total_frames"] > 0

    # Test frames
    frames = await bridge.get_available_frames()
    assert len(frames) > 0
    assert "name" in frames[0]

    print("All tests passed!")

asyncio.run(test_bridge())
```

## Migration Guide

If you were using the old API:

```python
# OLD (no longer works)
response = IPCResponse.success(result, request_id)
response = IPCResponse.error(error, request_id)

# NEW (required)
response = IPCResponse.create_success(result, request_id)
response = IPCResponse.create_error(error_obj=error, request_id=request_id)
```

## Benefits

1. **No Hard Dependencies** - Protocol and minimal bridge work standalone
2. **Testable** - Develop and test CLI without full Warden installation
3. **Graceful Degradation** - Returns minimal data instead of crashing
4. **Mock Data** - Realistic test data for rapid development
5. **Backward Compatible** - Full functionality when Warden is installed
