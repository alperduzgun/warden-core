# Correlation ID Implementation (Issue #20)

## Overview

This document describes the implementation of end-to-end request tracing using correlation IDs (scan_id) for the Warden Core validation pipeline.

## Problem Statement

Prior to this implementation, it was difficult to trace a single pipeline execution through all the log messages, especially when multiple scans were running concurrently. This made debugging and monitoring challenging.

## Solution

Added automatic correlation ID (`scan_id`) tracking that appears in ALL log messages during a pipeline execution.

### Key Features

1. **Automatic Binding**: `scan_id` is automatically bound to structlog context vars at the start of pipeline execution
2. **Automatic Propagation**: All log messages automatically include the `scan_id` without manual intervention
3. **Automatic Cleanup**: `scan_id` is automatically unbound after pipeline completion
4. **8-Character Format**: Uses first 8 characters of UUID for compact, readable IDs
5. **Metadata Inclusion**: `scan_id` is included in pipeline result metadata

## Implementation Details

### 1. Orchestrator Changes (`src/warden/pipeline/application/orchestrator/orchestrator.py`)

**Added import:**
```python
import structlog
```

**Bind scan_id at pipeline start (line ~232):**
```python
# Bind scan_id to context vars for correlation tracking (Issue #20)
scan_id = str(uuid4())[:8]
structlog.contextvars.bind_contextvars(scan_id=scan_id)

logger.info(
    "pipeline_execution_started",
    pipeline_id=context.pipeline_id,
    scan_id=scan_id,  # Now logged
    file_count=len(code_files),
    frames_override=frames_to_execute,
)
```

**Unbind scan_id in finally block (line ~452):**
```python
finally:
    # Cleanup and state consistency - always run regardless of success/failure
    await self._cleanup_on_completion_async(context)
    self._ensure_state_consistency(context)

    # Unbind scan_id from context vars (Issue #20)
    structlog.contextvars.unbind_contextvars("scan_id")
```

**Include scan_id in metadata (line ~851):**
```python
metadata={
    "strategy": self.config.strategy.value,
    "fail_fast": self.config.fail_fast,
    "scan_id": scan_id if 'scan_id' in locals() else None,
    "advisories": getattr(context, "advisories", []),
    ...
}
```

### 2. LLM Factory Silent Failure Fix (`src/warden/llm/factory.py`)

**Fixed silent exception in create_client (line ~98):**
```python
except Exception as e:
    # Issue #20: Log provider fallback failures for visibility
    logger.warning("fast_tier_client_creation_failed", provider=fast_provider.value, error=str(e))
```

**Fixed silent exception in create_client_with_fallback_async (line ~138):**
```python
except Exception as e:
    # Issue #20: Log provider fallback failures for visibility
    _logger.warning("provider_fallback_failed", provider=provider.value, error=str(e))
    continue
```

### 3. Frame Registry Discovery Logging (`src/warden/validation/infrastructure/frame_registry.py`)

**Promoted ImportError from debug to warning (line ~395):**
```python
except ImportError as e:
    # Issue #20: Promote to warning for visibility
    logger.warning(
        "builtin_frame_import_failed",
        frame_name=frame_path.name,
        error=str(e),
    )
```

**Promoted general exceptions from error to warning (line ~402):**
```python
except Exception as e:
    # Issue #20: Promote to warning for visibility
    logger.warning(
        "builtin_frame_discovery_error",
        frame_name=frame_path.name,
        error=str(e),
        error_type=type(e).__name__,
    )
```

## How It Works

### Structlog Context Vars

The implementation leverages structlog's `merge_contextvars` processor that was already configured in `src/warden/shared/infrastructure/logging.py`:

```python
shared_processors: list[Any] = [
    structlog.contextvars.merge_contextvars,  # Already configured!
    structlog.stdlib.add_log_level,
    structlog.stdlib.add_logger_name,
    ...
]
```

When we call `structlog.contextvars.bind_contextvars(scan_id=scan_id)`, the scan_id is:
1. Stored in thread-local context vars
2. Automatically merged into every log message via the processor
3. Available across all modules without manual passing

### Example Log Output

Before (no correlation):
```
[info] pipeline_execution_started pipeline_id=abc123 file_count=5
[info] phase_started phase=VALIDATION
[info] frame_executed frame_id=security
```

After (with correlation):
```
[info] pipeline_execution_started pipeline_id=abc123 scan_id=9937dfc7 file_count=5
[info] phase_started phase=VALIDATION scan_id=9937dfc7
[info] frame_executed frame_id=security scan_id=9937dfc7
```

## Testing

Created comprehensive tests in `tests/infrastructure/test_correlation_ids.py`:

1. **test_scan_id_bound_to_context_vars**: Verifies scan_id appears in logs
2. **test_scan_id_in_pipeline_metadata**: Verifies scan_id in result metadata
3. **test_scan_id_unbind_after_pipeline**: Verifies cleanup after execution
4. **test_llm_factory_logs_provider_failures**: Verifies factory logging
5. **test_frame_registry_logs_discovery_errors**: Verifies registry logging

All tests pass successfully.

## Benefits

1. **Easy Debugging**: Filter logs by scan_id to see all events for a single scan
2. **Concurrent Execution**: Multiple scans can run without log interleaving confusion
3. **Audit Trail**: Complete trace of what happened during a specific scan
4. **Monitoring**: Track scan performance and identify bottlenecks
5. **Error Correlation**: Easily find all related errors for a failed scan

## Usage Examples

### Filtering Logs by Scan ID

```bash
# Filter all logs for a specific scan
warden scan . 2>&1 | grep "scan_id=abc12345"

# Extract just the scan_id from a log
grep "pipeline_execution_started" warden.log | jq -r '.scan_id'
```

### Programmatic Access

```python
# The scan_id is available in the result metadata
result, context = await orchestrator.execute_async([code_file])
scan_id = result.metadata['scan_id']
print(f"Scan completed with ID: {scan_id}")
```

### Monitoring Dashboard

The scan_id can be used to:
- Group related metrics in time-series databases
- Create trace visualizations
- Link logs to distributed tracing systems (e.g., Jaeger, DataDog)

## Related Issues

- Issue #20: Add correlation IDs for end-to-end request tracing
- Issue #18: Reduce silent error handling in orchestrator (partial fix via factory logging)

## Future Enhancements

1. **Distributed Tracing**: Integrate with OpenTelemetry for full trace context
2. **Correlation Across Services**: Pass scan_id to external LLM calls for full tracing
3. **Performance Tracking**: Use scan_id to aggregate performance metrics
4. **Error Aggregation**: Group errors by scan_id in error tracking systems
