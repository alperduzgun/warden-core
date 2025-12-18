# Mem0 Project Memory - Auto Mode

## Core Behavior

**ALWAYS on first message:** Check if conversation just started, then load context:
```bash
~/claude-mem0-integration/mem summary
```

**Save automatically (no asking):**
- Architectural decisions → `~/claude-mem0-integration/mem save-decision "X" "Y"`
- Bug fixes → `~/claude-mem0-integration/mem save "Bug: X. Solution: Y" --type error`
- API info → `~/claude-mem0-integration/mem save "..." --type api`
- Important code → `~/claude-mem0-integration/mem save-code "code" "desc" --language lang`

**Keep it subtle:** Just "✅" or "Noted" after saving. Don't explain the system.

**Search proactively:** Before major work, search: `~/claude-mem0-integration/mem search "topic"`

## Memory Types
- `note` - General information
- `decision` - Architectural decisions
- `error` - Bugs and solutions
- `api` - API endpoints
- `code` - Code patterns
- `config` - Configuration
- `todo` - Tasks

## TopTanTR Flutter Project Context
This is a B2B e-commerce mobile application with:
- Flutter/Dart framework
- Firebase integration (Auth, Analytics, Crashlytics)
- Microsoft Clarity analytics
- Smartlook session recording
- Real-time order tracking
- Multi-platform support (iOS, Android)
- Monorepo structure (mobile-workspace)

Always check memory first before implementing features.
