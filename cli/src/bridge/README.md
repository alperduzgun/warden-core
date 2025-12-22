# Warden TypeScript Client

TypeScript/Node.js client for communicating with Warden's Python backend via IPC.

## Installation

```bash
npm install
```

## Usage

### Basic Example

```typescript
import { WardenClient } from './bridge/wardenClient';

async function main() {
  const client = new WardenClient();

  try {
    // Connect to Python backend
    await client.connect();

    // Execute pipeline
    const result = await client.executePipeline('/path/to/file.py');
    console.log(`Status: ${result.status}`);
    console.log(`Findings: ${result.total_findings}`);

    // Disconnect
    await client.disconnect();
  } catch (error) {
    console.error('Error:', error);
  }
}

main();
```

### Configuration

```typescript
const client = new WardenClient({
  transport: 'stdio',           // or 'socket'
  socketPath: '/tmp/warden.sock', // for socket transport
  pythonPath: 'python3',        // path to Python executable
  timeoutMs: 30000,            // request timeout
});
```

### API Methods

#### `ping()`
Health check to verify connection.

```typescript
const pong = await client.ping();
// { status: 'ok', message: 'pong', timestamp: '...' }
```

#### `executePipeline(filePath, config?)`
Execute validation pipeline on a file.

```typescript
const result = await client.executePipeline('/path/to/file.py', {
  strategy: 'sequential',
  fail_fast: true,
});

console.log(result.status);
console.log(result.total_findings);
console.log(result.frame_results);
```

#### `getConfig()`
Get Warden configuration.

```typescript
const config = await client.getConfig();
console.log(config.version);
console.log(config.llm_providers);
console.log(config.frames);
```

#### `getAvailableFrames()`
List available validation frames.

```typescript
const frames = await client.getAvailableFrames();
for (const frame of frames) {
  console.log(`${frame.name} (${frame.priority})`);
}
```

#### `analyzeWithLLM(prompt, provider?)`
Analyze code with LLM (streaming).

```typescript
for await (const chunk of await client.analyzeWithLLM('Analyze this code')) {
  process.stdout.write(chunk);
}
```

### Error Handling

```typescript
try {
  const result = await client.executePipeline('/nonexistent/file.py');
} catch (error) {
  console.error('Error code:', error.code);    // -32001 (FILE_NOT_FOUND)
  console.error('Error message:', error.message);
  console.error('Error data:', error.data);
}
```

### Event Handling

```typescript
client.on('error', (error) => {
  console.error('Client error:', error);
});

client.on('stderr', (data) => {
  console.error('Python stderr:', data);
});

client.on('exit', (code) => {
  console.log('Python process exited with code:', code);
});
```

## Types

All TypeScript types are exported from `wardenClient.ts`:

```typescript
import {
  WardenClient,
  PipelineResult,
  FrameResult,
  Finding,
  WardenConfig,
  FrameInfo,
  LLMProvider,
} from './bridge/wardenClient';
```

## Testing

```bash
# Run the example
ts-node cli/src/bridge/wardenClient.ts

# Test with your own file
import { WardenClient } from './bridge/wardenClient';

const client = new WardenClient();
await client.connect();
const result = await client.executePipeline('./myfile.py');
console.log(result);
await client.disconnect();
```

## Architecture

```
┌─────────────────────────────────────┐
│  Ink CLI (React Components)         │
│                                     │
│  ┌───────────────────────────────┐ │
│  │  WardenClient (TypeScript)    │ │
│  │                               │ │
│  │  - executePipeline()          │ │
│  │  - getConfig()                │ │
│  │  - analyzeWithLLM()           │ │
│  └───────────────┬───────────────┘ │
└──────────────────┼───────────────────┘
                   │ JSON-RPC over STDIO
                   │
┌──────────────────▼───────────────────┐
│  Python Backend                      │
│                                      │
│  ┌────────────────────────────────┐ │
│  │  IPCServer                     │ │
│  │  ┌──────────────────────────┐  │ │
│  │  │  WardenBridge            │  │ │
│  │  │                          │  │ │
│  │  │  - Pipeline Orchestrator │  │ │
│  │  │  - LLM Integration       │  │ │
│  │  │  - Frame Factory         │  │ │
│  │  └──────────────────────────┘  │ │
│  └────────────────────────────────┘ │
└──────────────────────────────────────┘
```

## Troubleshooting

**Connection Issues**
- Ensure Python is available in PATH
- Check that `warden.cli_bridge` module is installed
- Verify virtual environment is activated

**Timeout Errors**
- Increase `timeoutMs` in client config
- Check Python process logs (stderr events)

**JSON Parse Errors**
- Ensure Python backend is sending line-delimited JSON
- Check for invalid UTF-8 characters in responses

## Contributing

When adding new IPC methods:

1. Add method to Python `WardenBridge` class
2. Add TypeScript method to `WardenClient` class
3. Add TypeScript types for request/response
4. Update documentation
5. Add tests

## License

MIT License
