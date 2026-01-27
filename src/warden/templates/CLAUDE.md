# Project Instructions

## Warden Integration

This project is protected by **Warden** (AI Code Guardian).

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
| `warden scan` | Full project scan |
| `warden scan --file <path>` | Scan single file |
| `warden status` | Quick status check |

### Rules

- Never skip Warden verification after code changes
- Never suppress errors without explicit user permission
- Report Warden score after significant changes

### Full Protocol

See `.warden/AI_RULES.md` for detailed verification protocol.
