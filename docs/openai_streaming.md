# OpenAI Streaming Implementation

## Overview

This document describes the OpenAI streaming implementation for the Warden Core project. The implementation provides true Server-Sent Events (SSE) streaming support for both OpenAI and Azure OpenAI providers, with automatic fallback to simulated streaming on errors.

## Features

### True SSE Streaming
- Real-time streaming of LLM responses using OpenAI's SSE protocol
- Supports both OpenAI and Azure OpenAI endpoints
- Yields content chunks as they arrive from the API
- Handles SSE event format: `data: {json}`

### Robust Error Handling
- Gracefully handles malformed JSON chunks
- Skips empty content chunks automatically
- Filters out SSE comments (lines starting with `:`)
- Falls back to simulated streaming if SSE fails

### Custom Model Support
- Override default model per request
- Works with both OpenAI models and Azure deployments

## Architecture

### Components

#### `stream_completion_async()`
Public method that provides streaming interface with error handling and fallback.

```python
async def stream_completion_async(
    self,
    prompt: str,
    system_prompt: str = "You are a helpful coding assistant.",
    model: Optional[str] = None
):
    """
    Streaming completion method using Server-Sent Events (SSE).

    Args:
        prompt: User prompt
        system_prompt: System prompt (optional)
        model: Model name override (optional)

    Yields:
        Completion chunks as they arrive from the API
    """
```

#### `_stream_with_sse()`
Internal method that handles the actual SSE streaming protocol.

```python
async def _stream_with_sse(
    self,
    prompt: str,
    system_prompt: str,
    model: Optional[str] = None
):
    """
    Internal method for true SSE streaming.

    Args:
        prompt: User prompt
        system_prompt: System prompt
        model: Model name override (optional)

    Yields:
        Content chunks from the streaming response
    """
```

## Usage Examples

### Basic Streaming

```python
from warden.llm.providers.openai import OpenAIClient
from warden.llm.config import ProviderConfig
from warden.llm.types import LlmProvider

# Create client
config = ProviderConfig(
    api_key="your-api-key",
    endpoint="https://api.openai.com/v1",
    default_model="gpt-4o",
    enabled=True
)
client = OpenAIClient(config, LlmProvider.OPENAI)

# Stream completion
async for chunk in client.stream_completion_async(
    prompt="Write a haiku about code",
    system_prompt="You are a helpful assistant."
):
    print(chunk, end="", flush=True)
```

### Azure OpenAI Streaming

```python
# Create Azure client
config = ProviderConfig(
    api_key="your-azure-key",
    endpoint="https://your-resource.openai.azure.com",
    default_model="gpt-4o",
    api_version="2024-02-01",
    enabled=True
)
client = OpenAIClient(config, LlmProvider.AZURE_OPENAI)

# Stream completion
async for chunk in client.stream_completion_async(
    prompt="Explain streaming",
    system_prompt="You are a technical writer."
):
    print(chunk, end="", flush=True)
```

### Custom Model

```python
# Override default model
async for chunk in client.stream_completion_async(
    prompt="Test prompt",
    system_prompt="Test system",
    model="gpt-3.5-turbo"
):
    print(chunk, end="", flush=True)
```

## SSE Protocol Details

### Event Format

OpenAI uses Server-Sent Events (SSE) protocol:

```
data: {"choices": [{"delta": {"content": "Hello"}}]}
data: {"choices": [{"delta": {"content": " world"}}]}
data: [DONE]
```

### Parsing Rules

1. **Empty lines**: Skipped
2. **Comment lines** (starting with `:`): Skipped
3. **Data lines**: Must start with `data: `
4. **Termination**: `data: [DONE]` signals end of stream
5. **Malformed JSON**: Skipped with silent error handling
6. **Empty content**: Chunks with no content are filtered out

### Response Structure

Each chunk follows this structure:

```json
{
  "choices": [
    {
      "delta": {
        "content": "chunk text"
      }
    }
  ]
}
```

## Error Handling

### SSE Streaming Failures

If SSE streaming fails for any reason:

1. Exception is caught and logged
2. System falls back to `complete_async()` non-streaming method
3. Full response is yielded in chunks (simulated streaming)
4. No user-facing error occurs

### Malformed JSON

Malformed JSON chunks are:

1. Caught by `json.JSONDecodeError`
2. Skipped silently
3. Logged for debugging
4. Don't interrupt the stream

### Network Errors

Network errors trigger:

1. Exception in `_stream_with_sse()`
2. Automatic fallback to non-streaming
3. Simulated chunking of complete response

## Testing

### Unit Tests

Comprehensive test suite in `tests/llm/test_openai_streaming.py`:

- `test_openai_streaming_success`: Basic SSE streaming
- `test_azure_openai_streaming_success`: Azure variant
- `test_openai_streaming_skips_empty_chunks`: Empty content filtering
- `test_openai_streaming_handles_malformed_json`: JSON error handling
- `test_openai_streaming_skips_comments_and_empty_lines`: SSE protocol compliance
- `test_openai_streaming_fallback_on_error`: Fallback mechanism
- `test_openai_streaming_with_custom_model`: Custom model support

### Running Tests

```bash
# Run streaming tests only
python3 -m pytest tests/llm/test_openai_streaming.py -v

# Run all LLM tests
python3 -m pytest tests/llm/ -v
```

### Manual Demo

Run the manual demo script to see streaming in action with real API:

```bash
python3 tests/llm/manual_streaming_demo.py
```

Requires environment variables:
- `OPENAI_API_KEY` for OpenAI demo
- `AZURE_OPENAI_API_KEY` and `AZURE_OPENAI_ENDPOINT` for Azure demo

## Performance Considerations

### Benefits of Streaming

1. **Lower latency**: First tokens arrive faster
2. **Better UX**: Progressive display of results
3. **Memory efficient**: Processes chunks incrementally

### Trade-offs

1. **Token counting**: Not available until stream completes
2. **Error recovery**: Partial responses on mid-stream failures
3. **Network overhead**: SSE connection maintained throughout

## Comparison with Non-Streaming

| Feature | Streaming | Non-Streaming |
|---------|-----------|---------------|
| First token latency | Low | High |
| Total response time | Similar | Similar |
| Token usage info | Not available | Available |
| Memory usage | Constant | Buffered |
| Error handling | Partial results | All-or-nothing |
| Retry logic | Not applicable | Full retry |

## Future Enhancements

### Potential Improvements

1. **Token counting**: Accumulate token usage during stream
2. **Reconnection logic**: Auto-reconnect on mid-stream failures
3. **Compression**: Support SSE compression if available
4. **Multiplexing**: Stream multiple requests concurrently
5. **Cancellation**: Support for aborting mid-stream

### OpenAI SDK Migration

Currently using raw `httpx` for SSE. Could migrate to official OpenAI SDK:

```python
# Future approach with OpenAI SDK
from openai import AsyncOpenAI

client = AsyncOpenAI(api_key="...")
stream = await client.chat.completions.create(
    model="gpt-4o",
    messages=[...],
    stream=True
)

async for chunk in stream:
    print(chunk.choices[0].delta.content or "", end="")
```

**Trade-offs:**
- **Pro**: Official SDK, maintained by OpenAI
- **Pro**: Built-in retry logic
- **Con**: Additional dependency
- **Con**: Less control over low-level details

## References

- [OpenAI Streaming Documentation](https://platform.openai.com/docs/api-reference/streaming)
- [Server-Sent Events Specification](https://html.spec.whatwg.org/multipage/server-sent-events.html)
- [httpx Streaming Guide](https://www.python-httpx.org/advanced/#streaming-responses)

## Changelog

### 2026-02-11
- Initial implementation of SSE streaming
- Support for OpenAI and Azure OpenAI
- Fallback mechanism for errors
- Comprehensive test suite
- Documentation and demo scripts
