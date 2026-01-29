# Project Instructions

## Warden Integration

This project is protected by **Warden** (AI Code Guardian).

### IMPORTANT: First-Time Setup Check

**Before doing any work**, verify Warden setup is complete:

1. **If MCP is available**: Call `warden_setup_status` tool first
   - If `ready_for_use: false` → Help user complete missing steps
   - Follow `ai_guidance` instructions in the response

2. **If MCP not available**: Check these files exist:
   - `.warden/config.yaml` - If missing, run: `warden init`
   - `.warden/ai_status.md` - If missing, run: `warden scan`

### Startup Protocol

1. **Read status first**: Check `.warden/ai_status.md`
   - If `PASS`: Proceed normally
   - If `FAIL`: Fix issues before other work
   - If `PENDING`: Run initial scan

2. **After code changes**: Run `warden scan`

3. **Before commit**: Ensure Warden status is PASS

### Commands

| Command | Description |
|---------|-------------|
| `warden init` | Initialize Warden in project |
| `warden scan` | Full project scan |
| `warden scan --file <path>` | Scan single file |
| `warden status` | Quick status check |

### MCP Tools (if available)

| Tool | Description |
|------|-------------|
| `warden_setup_status` | Check setup completeness (use FIRST) |
| `warden_scan` | Run security scan |
| `warden_status` | Get project health status |
| `warden_health_check` | Check service availability |

### Rules

- Never skip Warden verification after code changes
- Never suppress errors without explicit user permission
- Report Warden score after significant changes

### Full Protocol

See `.warden/AI_RULES.md` for detailed verification protocol.
