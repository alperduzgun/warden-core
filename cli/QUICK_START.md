# Warden Ink CLI - Quick Start Guide

## 🚀 Installation & Setup

### Prerequisites
- Node.js 20+
- Python 3.11+ (for IPC backend)
- npm installed

### Install Dependencies
```bash
cd /Users/alper/Documents/Development/Personal/warden-core/cli
npm install
npm run build
npm link  # Make warden-chat globally available
```

---

## 🎯 Usage

### Option 1: Global Command (Recommended)
```bash
warden-chat
```

### Option 2: npm start
```bash
cd /Users/alper/Documents/Development/Personal/warden-core/cli
npm start
```

### Option 3: Direct Node
```bash
node /Users/alper/Documents/Development/Personal/warden-core/cli/dist/index.js
```

---

## 📝 Available Commands

### Commands That Work WITHOUT IPC Backend

#### 1. Help Command
```
/help
```
Shows comprehensive help with all available commands.

#### 2. Clear Chat
```
/clear
```
Clears all messages from chat history.

#### 3. Quit
```
/quit
```
Exits the CLI gracefully.

---

### Commands That REQUIRE IPC Backend

For these commands, you need Python backend running in a separate terminal:

```bash
# Terminal 1: Start Python IPC Server
cd /Users/alper/Documents/Development/Personal/warden-core
source .venv/bin/activate
python3 start_ipc_server.py
```

Then in Terminal 2, run CLI and use these commands:

#### 4. Status Command
```
/status
```
Shows:
- Session ID
- IPC connection status
- Active LLM providers
- Loaded validation frames

#### 5. Analyze Command
```
/analyze <file_path>

# Example:
/analyze ../test_sample.py
/analyze src/main.py
```
Analyzes a Python file with full Warden pipeline:
- Runs all validation frames
- Detects security issues
- Shows findings with severity levels

---

## 🧪 Quick Test

### Test 1: Basic Commands (No Backend Needed)
```bash
# Start CLI
warden-chat

# In CLI, type:
/help
/clear
/quit
```

### Test 2: Full Pipeline Analysis (Backend Required)

**Terminal 1: Python Backend**
```bash
cd /Users/alper/Documents/Development/Personal/warden-core
source .venv/bin/activate
python3 start_ipc_server.py
```

**Terminal 2: CLI**
```bash
warden-chat

# In CLI:
/status
/analyze test_sample.py
```

**Expected Output:**
- Pipeline execution progress
- Frame results (SecurityFrame, ChaosFrame, etc.)
- Security findings:
  - SQL injection vulnerability
  - Command injection
  - Hardcoded secrets

---

## 🎨 UI Features

- **Real-time Updates**: Messages stream as they arrive
- **Markdown Support**: Rich text formatting
- **Command Detection**: Auto-detects `/`, `@`, `!` commands
- **Error Handling**: Helpful error messages with troubleshooting

---

## ⚙️ Configuration

### Environment Variables
```bash
export WARDEN_API_URL="http://localhost:8000"
export WARDEN_TIMEOUT="30000"
export WARDEN_MAX_RETRIES="3"
```

### IPC Backend Configuration
Edit `.warden/config.yaml` for pipeline settings.

---

## 🐛 Troubleshooting

### Issue: "IPC connection not available"
**Solution:**
1. Check if Python backend is running:
   ```bash
   ps aux | grep "warden.cli_bridge.server"
   ```
2. Start the backend:
   ```bash
   cd /Users/alper/Documents/Development/Personal/warden-core
   source .venv/bin/activate
   python3 start_ipc_server.py
   ```

### Issue: "File not found"
**Solution:**
- Use absolute path: `/full/path/to/file.py`
- Or relative from current directory: `../test_sample.py`

### Issue: CLI won't start
**Solution:**
1. Rebuild TypeScript:
   ```bash
   npm run build
   ```
2. Check Node version:
   ```bash
   node --version  # Should be 20+
   ```

---

## 📊 Command Summary

| Command | IPC Required | Description |
|---------|--------------|-------------|
| `/help` | ❌ No | Show help information |
| `/status` | ✅ Yes | Show session status |
| `/clear` | ❌ No | Clear chat history |
| `/quit` | ❌ No | Exit CLI |
| `/analyze <file>` | ✅ Yes | Analyze code file |

---

## 🚧 Coming Soon

- `/scan [path]` - Scan entire directory
- `/validate <file>` - Run validation frames
- `/fix <file>` - Auto-fix issues
- `/rules` - Manage custom rules

---

## 📖 More Information

- Full test guide: `TEST_COMMANDS.md`
- Component documentation: `COMPONENTS.md`
- Architecture: See main README

---

## ✅ Verification

To verify everything is working:

```bash
# 1. Check global command
which warden-chat
# Output: /usr/local/bin/warden-chat (or similar)

# 2. Check build
ls dist/index.js
# Output: dist/index.js

# 3. Test help (no backend needed)
warden-chat
# Type: /help
# Should show full help text

# 4. Test with backend
# Terminal 1: python3 start_ipc_server.py
# Terminal 2: warden-chat
# Type: /status
# Should show connected status
```

---

**Ready to use!** Start with `/help` to explore all commands. 🚀
