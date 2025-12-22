# System Prompt: Warden Core Engine - Python Backend Integration

You are tasked with integrating the Warden Core validation framework with the Ink CLI. The Ink CLI is fully functional but returns "Warden validation framework not available" errors because the Python backend (IPC server) isn't properly initializing the PipelineOrchestrator.

## Context

**Project:** Warden - AI-powered code security scanner
**Location:** `/Users/alper/Documents/Development/Personal/warden-core/`
**Goal:** Make validation pipeline accessible from Ink CLI

## Current State

### ✅ Working
- Ink CLI (TypeScript/React) - All 9 commands registered
- IPC communication (Node ↔ Python socket)
- File picker with @ syntax
- Path resolution
- TUI version works perfectly

### ❌ Broken  
- Validation framework initialization in IPC server
- PipelineOrchestrator not loading
- Config/frame imports failing
- Returns mock data instead of real findings

## Your Mission

**Fix the Python backend so `/scan` and `/analyze` commands return real validation results.**

### Key Approach

1. **Study the TUI** - `src/warden/tui/` shows WORKING implementation
2. **Compare with IPC** - `start_ipc_server.py` and `src/warden/cli_bridge/` need fixing
3. **Initialize Pipeline** - PipelineOrchestrator requires proper setup
4. **Load Frames** - Validation frames must be imported and registered
5. **Test End-to-End** - `/scan @examples/` should show real findings

### Critical Files

**Reference (WORKING):**
- `src/warden/tui/app.py` - How TUI initializes orchestrator
- `src/warden/tui/commands/scan.py` - Working scan implementation

**To Fix:**
- `start_ipc_server.py` - IPC server entry point
- `src/warden/cli_bridge/` - IPC server handlers  
- Pipeline initialization code

**Core Engine:**
- `src/warden/pipeline/application/orchestrator.py` - Pipeline executor
- `src/warden/validation/` - Frame system
- `src/warden/config/` - Configuration loading

## Investigation Steps

1. Read `start_ipc_server.py` completely
2. Find how TUI initializes PipelineOrchestrator
3. Identify missing initialization in IPC server
4. Add PipelineOrchestrator setup to IPC server
5. Test frame loading and imports
6. Verify config loading
7. Test `/scan @examples/` from CLI

## Success Criteria

**Complete when:**
- `/scan @src/` shows real validation findings (not "framework not available")
- `/analyze file.py` returns actual security issues
- Progress updates show frame execution
- Results match TUI output

**Example Expected Output:**
```
> /scan @examples/

🔍 Scanning: /path/to/examples
📊 Found 8 Python files

🚀 Pipeline started - 5 frames on 8 files

✅ SQLInjectionFrame [1/5] Issues: 2 | 0.3s
✅ XSSFrame [2/5] Issues: 0 | 0.2s  
✅ PathTraversalFrame [3/5] Issues: 1 | 0.4s

📊 Summary: 3 issues (1 critical, 2 high)
```

## Debugging Tips

- Add verbose logging to IPC server
- Test imports manually: `python3 -c "from warden.pipeline.application.orchestrator import PipelineOrchestrator"`
- Check venv activation
- Compare TUI vs IPC initialization side-by-side
- Look for import errors in console

## Important Notes

- **Focus:** Python backend ONLY (TypeScript CLI is done)
- **Reference:** TUI works - copy its patterns
- **Test:** Real validation results, not mocks
- **Don't break:** Existing Ink CLI functionality

## Quick Start

```bash
cd /Users/alper/Documents/Development/Personal/warden-core

# Check what's broken
python3 start_ipc_server.py
# Then in another terminal:
warden-chat
> /scan @examples/

# Read reference implementation
cat src/warden/tui/app.py
cat src/warden/tui/commands/scan.py

# Find the gap
diff <how TUI initializes> <how IPC initializes>
```

Start by reading `start_ipc_server.py` and comparing it with TUI initialization. Good luck!
