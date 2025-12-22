# Warden CLI - Real World Testing Guide

## 🧪 Test Commands

### Test 1: Help Command (No IPC Required)
```bash
cd /Users/alper/Documents/Development/Personal/warden-core/cli
npm start

# In CLI:
/help
```

**Expected Output:**
- Full help text with all commands
- Command descriptions
- Keyboard shortcuts
- Pro tips

---

### Test 2: Status Command (Requires IPC)
```bash
# Terminal 1: Start IPC Server
cd /Users/alper/Documents/Development/Personal/warden-core
source .venv/bin/activate
python3 start_ipc_server.py

# Terminal 2: Start CLI
cd /Users/alper/Documents/Development/Personal/warden-core/cli
npm start

# In CLI:
/status
```

**Expected Output:**
- Session ID
- IPC connection status (✅ Connected)
- LLM provider configuration
- Active validation frames list
- Blocker frames count

---

### Test 3: Clear Command (No IPC Required)
```bash
cd /Users/alper/Documents/Development/Personal/warden-core/cli
npm start

# In CLI:
/help
/status
/clear
```

**Expected Output:**
- All previous messages cleared
- "✨ Chat history cleared." message

---

### Test 4: Quit Command (No IPC Required)
```bash
cd /Users/alper/Documents/Development/Personal/warden-core/cli
npm start

# In CLI:
/quit
```

**Expected Output:**
- "👋 Goodbye! Thanks for using Warden CLI." message
- CLI exits gracefully after 500ms

---

### Test 5: Analyze Command (Requires IPC)
```bash
# Terminal 1: Start IPC Server
cd /Users/alper/Documents/Development/Personal/warden-core
source .venv/bin/activate
python3 start_ipc_server.py

# Terminal 2: Start CLI
cd /Users/alper/Documents/Development/Personal/warden-core/cli
npm start

# In CLI:
/analyze ../test_sample.py
```

**Expected Output:**
- "🔍 Analyzing: test_sample.py" message
- Pipeline execution progress
- Pipeline summary:
  - Status (SUCCESS/FAILED)
  - Duration
  - Total frames
  - Frames passed/failed
- Findings summary:
  - Total findings
  - Critical/High/Medium/Low counts
- Frame results for each validation frame
- Detailed findings:
  - SQL injection in get_user()
  - Command injection in run_command()
  - Hardcoded secrets (API_KEY, PASSWORD)

---

### Test 6: Error Handling - Missing File
```bash
cd /Users/alper/Documents/Development/Personal/warden-core/cli
npm start

# In CLI:
/analyze nonexistent.py
```

**Expected Output:**
- "❌ File not found: /path/to/nonexistent.py"
- Helpful error message

---

### Test 7: Error Handling - No IPC Connection
```bash
# DON'T start IPC server
cd /Users/alper/Documents/Development/Personal/warden-core/cli
npm start

# In CLI:
/analyze ../test_sample.py
```

**Expected Output:**
- "❌ IPC connection not available"
- Troubleshooting steps:
  1. Python virtual environment is activated
  2. IPC server is running
  3. CLI is started with IPC enabled

---

### Test 8: Error Handling - Unknown Command
```bash
cd /Users/alper/Documents/Development/Personal/warden-core/cli
npm start

# In CLI:
/unknown
```

**Expected Output:**
- "❌ Unknown command: /unknown"
- "Use /help to see available commands."

---

## 📊 Test Results Template

| Test | Command | IPC Required | Status | Notes |
|------|---------|--------------|--------|-------|
| 1 | `/help` | No | ⬜ | |
| 2 | `/status` | Yes | ⬜ | |
| 3 | `/clear` | No | ⬜ | |
| 4 | `/quit` | No | ⬜ | |
| 5 | `/analyze` | Yes | ⬜ | |
| 6 | Error: Missing file | No | ⬜ | |
| 7 | Error: No IPC | No | ⬜ | |
| 8 | Error: Unknown cmd | No | ⬜ | |

---

## 🚀 Quick Test Script

```bash
#!/bin/bash
# Run all tests quickly

echo "🧪 Warden CLI - Quick Test Suite"
echo "================================"

cd /Users/alper/Documents/Development/Personal/warden-core/cli

echo ""
echo "Test 1: Help Command"
echo "Expected: Full help text"
echo "Command: /help"
echo ""

echo "Test 2: Clear Command"
echo "Expected: Chat history cleared"
echo "Command: /clear"
echo ""

echo "Test 3: Quit Command"
echo "Expected: Graceful exit"
echo "Command: /quit"
echo ""

echo "⚠️  Tests 2, 5 require IPC server running in separate terminal"
echo "   Terminal 1: python3 start_ipc_server.py"
echo "   Terminal 2: npm start"
echo ""

echo "To run interactive tests, execute:"
echo "  npm start"
```

---

## ✅ Success Criteria

- [x] All handlers compile without TypeScript errors
- [ ] `/help` shows comprehensive command list
- [ ] `/status` connects to IPC and shows config
- [ ] `/clear` removes all messages
- [ ] `/quit` exits gracefully
- [ ] `/analyze` executes pipeline and shows results
- [ ] Error messages are helpful and actionable
- [ ] UI renders correctly in terminal
- [ ] No crashes or exceptions

---

## 🐛 Known Issues

1. **stdin raw mode error in non-interactive shells**
   - This is expected when running via `Bash` tool
   - Works fine in real terminal

2. **IPC connection timeout**
   - Ensure Python backend is running
   - Check virtual environment is activated

---

## 📝 Next Steps After Testing

1. Fix any discovered bugs
2. Implement `/scan` handler (live progress)
3. Implement remaining commands (`/validate`, `/fix`, `/rules`)
4. Write unit tests
5. Update documentation
