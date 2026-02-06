# 🦞 OpenClaw for Warden Core - Quick Start

OpenClaw is now integrated with Warden Core for continuous development automation!

## ✅ What's Installed

- **OpenClaw 2026.2.3-1** ✓
- **Node.js 22.22.0** ✓
- **4 Custom Warden Skills** ✓
- **Helper Script** ✓

## 🎯 Custom Skills Available

| Skill | Status | Description |
|-------|--------|-------------|
| 🛡️ warden-scan | ✓ Ready | Run security scans |
| 🚧 warden-blockers | ✓ Ready | Track release blockers |
| 🧪 warden-test | ⚠️ Needs pytest | Run test suite |
| ✔️ warden-pre-commit | ⚠️ Needs pytest | Pre-commit quality gate |

## 🚀 Immediate Actions

### 1. Test a Simple Skill

```bash
# From warden-core directory
./.openclaw-helper.sh agent "check warden blockers"
```

This will analyze `temp/eksik_listesi.md` and show release blocker status.

### 2. Fix Missing Dependencies

```bash
# Install pytest if needed
pip install pytest

# Verify
pytest --version
```

### 3. Connect WhatsApp (Optional)

```bash
./.openclaw-helper.sh gateway
# Scan the QR code
# Send: "blocker status"
```

## 📱 Usage Patterns

### Command Line

```bash
# Check release blockers
./.openclaw-helper.sh agent "blocker status"

# Run security scan (once warden is in PATH)
./.openclaw-helper.sh agent "scan warden"

# Run tests
./.openclaw-helper.sh agent "run warden tests"

# Pre-commit check
./.openclaw-helper.sh agent "pre-commit check"
```

### WhatsApp/Telegram (after gateway setup)

```
"blocker status"           → Get instant blocker count
"scan warden"              → Run security scan
"run warden tests"         → Execute test suite
"pre-commit check"         → Quality gate check
```

## 🔧 Configuration Files

```
~/.openclaw/
  ├── skills/
  │   ├── warden-blockers/
  │   ├── warden-scan/
  │   ├── warden-test/
  │   └── warden-pre-commit/
  └── agents/

warden-core/
  ├── .openclaw-helper.sh       ← Helper script
  ├── docs/OPENCLAW_SETUP.md    ← Full documentation
  └── OPENCLAW_QUICKSTART.md    ← This file
```

## 🎮 Next Steps

### Level 1: Command Line (5 min)
```bash
./.openclaw-helper.sh agent "blocker status"
```

### Level 2: Gateway Setup (10 min)
```bash
./.openclaw-helper.sh configure
# Follow prompts to set up gateway mode
```

### Level 3: WhatsApp Integration (15 min)
```bash
./.openclaw-helper.sh gateway
# Scan QR code
# Text: "blocker status"
```

### Level 4: Scheduled Tasks (20 min)
Edit `~/.openclaw/config.json`:
```json
{
  "schedules": {
    "morning-briefing": {
      "cron": "0 9 * * *",
      "skill": "warden-blockers"
    }
  }
}
```

### Level 5: Git Integration (10 min)
```bash
# Add pre-commit hook
cat > .git/hooks/pre-commit << 'EOF'
#!/bin/bash
./.openclaw-helper.sh agent "pre-commit check"
EOF

chmod +x .git/hooks/pre-commit
```

## 🐛 Troubleshooting

### "command not found: openclaw"
Use the helper script:
```bash
./.openclaw-helper.sh <command>
```

### "Node version mismatch"
Helper script handles this automatically.

### "Skill not found"
```bash
./.openclaw-helper.sh skills list | grep warden
```

### "pytest not found"
```bash
pip install pytest
```

## 📊 Verify Installation

```bash
# Check version
./.openclaw-helper.sh --version
# Should output: 2026.2.3-1

# List skills
./.openclaw-helper.sh skills list | grep warden
# Should show 4 warden skills

# Run doctor
./.openclaw-helper.sh doctor
# Check for any critical issues
```

## 🎯 Recommended First Test

```bash
# Simple test with no dependencies
./.openclaw-helper.sh agent "check warden blockers"
```

Expected output:
```
🚧 Warden Release Blockers
Total: 43
Fixed: 38 ✅
Remaining: 5
Progress: 88%
```

## 📚 Full Documentation

See `docs/OPENCLAW_SETUP.md` for:
- Detailed gateway setup
- All skill descriptions
- Advanced configurations
- Scheduling tasks
- Git hook examples

---

**Ready to automate? Run the first test above! 🚀**
