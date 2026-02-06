# Orchestrator Fixes (ID 1, 3, 29)

## Status: PARTIALLY IMPLEMENTED

### ID 3: COMPLETED_WITH_FAILURES Status
✅ **DONE**: Enum added to `PipelineStatus` (line 23 in enums.py)
⏳ **TODO**: Integrate into orchestrator logic (see code below)

### ID 29: Timeout Enforcement  
⏳ **CRITICAL**: Add `asyncio.wait_for()` wrapper

### ID 1: Exception Handling & Cleanup
✅ **DONE**: Cleanup in `finally` block already exists (lines 424-428)
⏳ **NEEDS**: Better rollback on partial failure

## Quick Implementation Guide

### Step 1: Timeout Wrapper (ID 29)
In `orchestrator.py` line 259, wrap execution:

```python
import asyncio  # Add to imports

async def execute_pipeline_async(...):
    # ...existing setup code...
    
    try:
        # Wrap main execution in timeout
        timeout = self.config.timeout  # Default 300s
        async def _pipeline_execution():
            # All phase execution code here (lines 261-401)
            pass
        
        await asyncio.wait_for(_pipeline_execution(), timeout=timeout)
        
    except asyncio.TimeoutError:
        self.pipeline.status = PipelineStatus.FAILED
        error_msg = f"Pipeline timeout ({timeout}s)"
        context.errors.append(error_msg)
        logger.error("pipeline_timeout", timeout=timeout)
        raise RuntimeError(error_msg)
    except Exception as e:
        # ... existing error handling ...
```

### Step 2: Status Machine Fix (ID 3)
Replace lines 366-386 with:

```python
# Check blocker vs non-blocker failures
blocker_failures = []
non_blocker_failures = []

for fr in context.frame_results.values():
    result = fr.get('result')
    if result and result.status == "failed":
        if result.is_blocker:
            blocker_failures.append(fr)
        else:
            non_blocker_failures.append(fr)

# Status logic (ID 3 fix)
if has_errors or blocker_failures:
    self.pipeline.status = PipelineStatus.FAILED
elif non_blocker_failures:
    self.pipeline.status = PipelineStatus.COMPLETED_WITH_FAILURES
else:
    self.pipeline.status = PipelineStatus.COMPLETED
```

## Testing
```bash
# Test timeout
warden scan --timeout 10 large-project/

# Test partial failures
warden scan project-with-warnings/
```
