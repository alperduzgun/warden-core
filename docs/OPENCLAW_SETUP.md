# OpenClaw Integration Guide

OpenClaw is now configured to accelerate Warden Core development through automated tasks and natural language commands.

## 🎯 What's Configured

### Custom Skills Created

1. **warden-test** 🧪
   - Run test suite
   - Get instant pass/fail notifications
   - Coverage reports

2. **warden-scan** 🛡️
   - Security scans on demand
   - Branch-aware scanning
   - Instant notifications

3. **warden-blockers** 🚧
   - Track release blocker status
   - Progress monitoring
   - Daily briefings

4. **warden-pre-commit** ✔️
   - Quality gate checks
   - Automated pre-commit validation
   - Block commits on failures

## 🚀 Quick Start

### Option 1: Using Helper Script (Recommended)

```bash
# From Warden Core directory
./.openclaw-helper.sh --help
```

### Option 2: Direct Command

```bash
# Ensure Node 22 is in PATH
export PATH="/opt/homebrew/opt/node@22/bin:$PATH"
openclaw --help
```

### Option 3: Add to Shell Profile

Add to `~/.zshrc`:
```bash
export PATH="/opt/homebrew/opt/node@22/bin:$PATH"
alias oclaw="openclaw"
```

Then reload: `source ~/.zshrc`

## 📱 Connecting Messaging Apps

### WhatsApp Integration

```bash
openclaw gateway
# Scan QR code with WhatsApp
# Now send: "run warden tests"
```

### Telegram Integration

```bash
# Create bot via @BotFather
export OPENCLAW_TELEGRAM_TOKEN="your-token"
openclaw gateway
```

### Discord Integration

```bash
export OPENCLAW_DISCORD_TOKEN="your-token"
openclaw gateway
```

## 🎮 Usage Examples

### Via Command Line

```bash
# Run tests
./.openclaw-helper.sh agent "run warden tests"

# Quick scan
./.openclaw-helper.sh agent "scan warden"

# Check blockers
./.openclaw-helper.sh agent "blocker status"

# Pre-commit check
./.openclaw-helper.sh agent "pre-commit check"
```

### Via WhatsApp/Telegram

```
You: "run warden tests"
OpenClaw:
🧪 Test Results
✅ 45/45 tests passed
Coverage: 87%
Status: PASS

You: "blocker status"
OpenClaw:
🚧 Release Blockers
Fixed: 38/43 (88%)
Critical: 1 remaining
High: 2 remaining
Status: ⚠️ NOT READY

You: "scan warden"
OpenClaw:
🛡️ Scan Complete
Branch: feature/new-validator
Critical: 0
High: 0
Status: ✅ PASS
```

## 🔧 Custom Skills Location

All Warden-specific skills are in:
```
~/.openclaw/skills/
  ├── warden-test/
  ├── warden-scan/
  ├── warden-blockers/
  └── warden-pre-commit/
```

## 📊 Scheduled Tasks

Set up automatic daily checks:

```javascript
// Add to ~/.openclaw/config.json
{
  "schedules": {
    "daily-blocker-check": {
      "cron": "0 9 * * *",  // Every day at 9 AM
      "skill": "warden-blockers"
    },
    "nightly-full-scan": {
      "cron": "0 22 * * *",  // Every day at 10 PM
      "skill": "warden-scan"
    }
  }
}
```

## 🎯 Git Integration

### Pre-commit Hook

Create `.git/hooks/pre-commit`:
```bash
#!/bin/bash
export PATH="/opt/homebrew/opt/node@22/bin:$PATH"

echo "🔍 Running pre-commit checks..."
openclaw agent "pre-commit check"

if [ $? -ne 0 ]; then
  echo "❌ Pre-commit checks failed. Commit blocked."
  exit 1
fi

echo "✅ All checks passed. Proceeding with commit."
```

Make it executable:
```bash
chmod +x .git/hooks/pre-commit
```

## 🔐 Security Notes

- Skills run with your local permissions
- No credentials stored in skills
- All data stays local
- WhatsApp/Telegram connections are end-to-end encrypted

## 🐛 Troubleshooting

### "Node version mismatch"
```bash
# Always use the helper script or set PATH
export PATH="/opt/homebrew/opt/node@22/bin:$PATH"
```

### "Skill not found"
```bash
# List all skills
openclaw skills list

# Reload skills
openclaw skills reload
```

### "Gateway connection issues"
```bash
# Reset gateway
openclaw gateway --reset

# Check logs
tail -f ~/.openclaw/logs/gateway.log
```

## 📚 Next Steps

1. **Connect a messaging app** for remote control
2. **Set up scheduled tasks** for daily briefings
3. **Create custom skills** for your workflow
4. **Add git hooks** for automated quality gates

## 🤝 Support

- OpenClaw Docs: https://docs.openclaw.ai
- Warden Core Issues: https://github.com/your-repo/warden-core/issues
- Skill Examples: `~/.openclaw/skills/`

---

**Happy Automating! 🦞**
