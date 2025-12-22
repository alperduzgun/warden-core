# Warden CLI Bridge - IPC Communication Layer

The Warden CLI Bridge provides a JSON-RPC 2.0 based IPC (Inter-Process Communication) layer that enables seamless communication between Warden's Python backend and the Ink-based CLI frontend.

## Architecture Overview

```
┌─────────────────┐         IPC (JSON-RPC)        ┌──────────────────┐
│   Ink CLI       │◄──────────────────────────────►│  Python Backend  │
│  (Node.js/TS)   │   Unix Socket or STDIO        │    (Warden)      │
└─────────────────┘                                └──────────────────┘
```

### Components

1. **Protocol Layer (`protocol.py`)**
   - JSON-RPC 2.0 implementation
   - Request/Response types
   - Error handling with standard error codes
   - Streaming support via Server-Sent Events (SSE)

2. **Bridge Service (`bridge.py`)**
   - Core service exposing Warden functionality
   - Methods: execute_pipeline, get_config, analyze_with_llm, etc.
   - Type-safe async API

3. **IPC Server (`server.py`)**
   - Transport layer (Unix Socket / STDIO)
   - Request routing and method invocation
   - Connection management
   - Graceful shutdown handling

## JSON-RPC Methods

### 1. `ping()` - Health Check

**Request:**
```json
{
  "jsonrpc": "2.0",
  "method": "ping",
  "id": 1
}
```

**Response:**
```json
{
  "jsonrpc": "2.0",
  "result": {
    "status": "ok",
    "message": "pong",
    "timestamp": "2024-01-01T00:00:00"
  },
  "id": 1
}
```

### 2. `execute_pipeline(file_path, config?)` - Run Validation Pipeline

**Request:**
```json
{
  "jsonrpc": "2.0",
  "method": "execute_pipeline",
  "params": {
    "file_path": "/path/to/file.py",
    "config": {
      "strategy": "sequential",
      "fail_fast": true
    }
  },
  "id": 2
}
```

**Response:**
```json
{
  "jsonrpc": "2.0",
  "result": {
    "pipeline_id": "uuid",
    "pipeline_name": "Code Validation",
    "status": "completed",
    "duration": 2.5,
    "total_frames": 5,
    "frames_passed": 4,
    "frames_failed": 1,
    "frames_skipped": 0,
    "total_findings": 3,
    "critical_findings": 0,
    "high_findings": 1,
    "medium_findings": 2,
    "low_findings": 0,
    "frame_results": [...]
  },
  "id": 2
}
```

### 3. `get_config()` - Get Warden Configuration

**Request:**
```json
{
  "jsonrpc": "2.0",
  "method": "get_config",
  "id": 3
}
```

**Response:**
```json
{
  "jsonrpc": "2.0",
  "result": {
    "version": "0.1.0",
    "llm_providers": [
      {
        "name": "azure_openai",
        "model": "gpt-4",
        "endpoint": "https://api.openai.com",
        "enabled": true
      }
    ],
    "default_provider": "azure_openai",
    "frames": [...],
    "total_frames": 5
  },
  "id": 3
}
```

### 4. `analyze_with_llm(prompt, provider?, stream?)` - LLM Analysis

**Request:**
```json
{
  "jsonrpc": "2.0",
  "method": "analyze_with_llm",
  "params": {
    "prompt": "Analyze this code for security issues",
    "provider": "azure_openai",
    "stream": true
  },
  "id": 4
}
```

**Response (Non-streaming):**
```json
{
  "jsonrpc": "2.0",
  "result": {
    "chunks": ["Analysis result..."],
    "streaming": false
  },
  "id": 4
}
```

### 5. `get_available_frames()` - List Validation Frames

**Request:**
```json
{
  "jsonrpc": "2.0",
  "method": "get_available_frames",
  "id": 5
}
```

**Response:**
```json
{
  "jsonrpc": "2.0",
  "result": [
    {
      "id": "syntax-check",
      "name": "Syntax Validation",
      "description": "Validates code syntax",
      "priority": "CRITICAL",
      "is_blocker": true,
      "tags": ["syntax"]
    }
  ],
  "id": 5
}
```

## Error Handling

The bridge uses standard JSON-RPC 2.0 error codes plus Warden-specific codes:

### Standard Error Codes
- `-32700` - Parse error (invalid JSON)
- `-32600` - Invalid request
- `-32601` - Method not found
- `-32602` - Invalid params
- `-32603` - Internal error

### Warden-Specific Error Codes
- `-32000` - Pipeline execution error
- `-32001` - File not found
- `-32002` - Validation error
- `-32003` - Configuration error
- `-32004` - LLM error
- `-32005` - Timeout error

**Error Response Example:**
```json
{
  "jsonrpc": "2.0",
  "error": {
    "code": -32001,
    "message": "File not found: /path/to/file.py",
    "data": {
      "file_path": "/path/to/file.py",
      "type": "FileNotFoundError"
    }
  },
  "id": 1
}
```

## Usage

### Starting the IPC Server

#### CLI Command (Recommended)
```bash
# Start with STDIO transport (for subprocess communication)
warden ink

# Start with Unix socket
warden ink --socket /tmp/warden-ipc.sock
```

#### Programmatic Usage
```python
import asyncio
from warden.cli_bridge.server import run_ipc_server

# Run with STDIO
asyncio.run(run_ipc_server(transport="stdio"))

# Run with Unix socket
asyncio.run(run_ipc_server(
    transport="socket",
    socket_path="/tmp/warden-ipc.sock"
))
```

### Standalone Server
```bash
python -m warden.cli_bridge.server --transport stdio
python -m warden.cli_bridge.server --transport socket --socket-path /tmp/warden.sock
```

## Client Implementation (TypeScript)

See the Node.js CLI implementation for TypeScript client example:

```typescript
import { WardenClient } from './bridge/wardenClient';

const client = new WardenClient({ transport: 'stdio' });

// Execute pipeline
const result = await client.executePipeline('/path/to/file.py');

// Get config
const config = await client.getConfig();

// Stream LLM analysis
for await (const chunk of client.analyzeWithLLM('Analyze this code')) {
  console.log(chunk);
}
```

## Testing

Run the comprehensive test suite:

```bash
# Run all bridge tests
pytest tests/unit/cli_bridge/ -v

# Run specific test file
pytest tests/unit/cli_bridge/test_protocol.py -v
pytest tests/unit/cli_bridge/test_bridge.py -v
pytest tests/unit/cli_bridge/test_server.py -v

# Run with coverage
pytest tests/unit/cli_bridge/ --cov=src/warden/cli_bridge --cov-report=html
```

## Transport Modes

### STDIO (Standard Input/Output)
- Best for subprocess communication
- Line-delimited JSON messages
- Automatic cleanup on process exit
- Use when launching Python as subprocess from Node.js

### Unix Socket
- Best for long-running services
- Multiple clients can connect
- Requires manual socket cleanup
- Use when running as a daemon or service

## Security Considerations

1. **API Keys**: Never send API keys over IPC - they're loaded from environment variables on the Python side
2. **File Access**: File paths are validated before processing
3. **Input Validation**: All inputs are validated using JSON-RPC 2.0 schema
4. **Error Messages**: Error messages don't expose sensitive system information

## Performance

- **Async I/O**: All operations are async for maximum throughput
- **Connection Pooling**: Reuses connections in socket mode
- **Streaming Support**: Large responses can be streamed (future enhancement)
- **Timeout Management**: Pipeline operations have configurable timeouts

## Future Enhancements

1. **True Streaming Support**: Implement SSE or WebSocket for real-time LLM streaming
2. **Bidirectional Events**: Push notifications from Python to Node.js
3. **Connection Authentication**: Add token-based authentication for socket mode
4. **Batch Requests**: Support JSON-RPC batch requests for parallel execution
5. **Metrics & Monitoring**: Export Prometheus metrics for monitoring

## Troubleshooting

### Common Issues

**1. "Module not found" errors**
- Ensure virtual environment is activated
- Run: `pip install -e .` from project root

**2. Socket connection refused**
- Check socket path permissions
- Ensure server is running
- Verify socket file exists

**3. Timeout errors**
- Increase `frame_timeout` in pipeline config
- Check for blocking operations in validation frames

**4. JSON parse errors**
- Ensure line-delimited JSON format (one message per line)
- Check for invalid UTF-8 characters

## Contributing

When adding new IPC methods:

1. Add method to `WardenBridge` class
2. Register method in `IPCServer.methods` dict
3. Add comprehensive tests (protocol, bridge, server)
4. Update this documentation
5. Add TypeScript types to Node.js client

## License

MIT License - See LICENSE file for details
