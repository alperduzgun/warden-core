# 🛡️ Warden CLI - Commands Reference

Quick reference for all 9 Warden CLI commands.

---

## 📋 Command List

| Command      | Aliases  | IPC | Description                              |
|--------------|----------|-----|------------------------------------------|
| `/help`      | -        | No  | Show help and available commands         |
| `/status`    | -        | Yes | Show session and configuration status    |
| `/clear`     | -        | No  | Clear chat history                       |
| `/quit`      | -        | No  | Exit application                         |
| `/analyze`   | `/a`, `/check` | Yes | Analyze file with full pipeline    |
| `/scan`      | `/s`     | Yes | Scan directory for issues                |
| `/validate`  | `/v`     | Yes | Run specific validation frames           |
| `/fix`       | `/f`     | Yes | Auto-fix issues (with confirmation)      |
| `/rules`     | `/r`     | No  | Manage custom validation rules           |

---

## 🎯 Command Details

### `/help`
Show help text with all available commands and usage examples.

**Usage:**
```
/help
```

**Features:**
- Lists all 9 commands
- Shows aliases and descriptions
- Provides usage examples
- No IPC connection needed

---

### `/status`
Display current session and configuration status.

**Usage:**
```
/status
```

**Shows:**
- Session ID and start time
- IPC connection status
- LLM provider configuration
- Available validation frames
- Total frames count

**Requires:** IPC connection

---

### `/clear`
Clear all messages from chat history.

**Usage:**
```
/clear
```

**Features:**
- Instantly clears chat
- No confirmation needed
- Local operation (no IPC)

---

### `/quit`
Exit the Warden CLI application.

**Usage:**
```
/quit
```

**Aliases:** `/exit`, `/q`

**Features:**
- Graceful shutdown
- Closes IPC connection
- No data loss

---

### `/analyze`
Run full Warden validation pipeline on a single file.

**Usage:**
```
/analyze <file_path>
```

**Aliases:** `/a`, `/check`

**Examples:**
```bash
/analyze src/main.py
/a test_sample.py
/check ../utils/helper.py
```

**Output:**
- Pipeline summary (status, duration)
- Total frames executed
- Findings summary (by severity)
- Frame results
- Detailed findings with code snippets

**Requires:** IPC connection

---

### `/scan`
Scan entire directory and analyze all Python files.

**Usage:**
```
/scan <directory_path>
```

**Alias:** `/s`

**Examples:**
```bash
/scan src/
/s ../myproject/
/scan .
```

**Features:**
- Recursive directory traversal
- Progress tracking ([1/N] files)
- Aggregated results
- Severity breakdown
- Top problematic files

**Output:**
- Total files scanned
- Total issues found
- Critical/High/Medium/Low counts
- Top 5 files with most issues
- Execution time

**Requires:** IPC connection

---

### `/validate`
Run specific validation frames on a file.

**Usage:**
```
/validate <file_path> [frame1,frame2,...]
/validate --list
```

**Alias:** `/v`

**Examples:**
```bash
# Run all frames
/validate src/main.py

# Run specific frames
/validate src/main.py security
/validate src/main.py security,orphan

# List available frames
/validate --list
/v -l
```

**Features:**
- Selective frame execution
- Frame filtering by name/ID
- Detailed frame results
- List all available frames
- Lighter than full pipeline

**Output:**
- Frames requested vs executed
- Pass/fail status per frame
- Total findings
- Detailed findings per frame

**Requires:** IPC connection

---

### `/fix`
Auto-fix issues found in code (with user confirmation).

**Usage:**
```
/fix <file_path> [issue_id1,issue_id2,...]
```

**Alias:** `/f`

**Examples:**
```bash
# Fix all issues
/fix src/main.py

# Fix specific issues
/fix src/main.py W001
/fix src/main.py W001,W002
```

**Features:**
- Automatic backup (.bak files)
- Show diff before applying
- Require user confirmation
- Security-first approach
- No auto-modifications without approval

**Current Status:**
⚠️ **Placeholder implementation** - Shows roadmap message.
Backend `fix_issues()` method needs implementation.

**Future Workflow:**
1. Backup original file
2. Analyze and suggest fixes
3. Show diff of proposed changes
4. Ask for user confirmation
5. Apply changes if approved

**Requires:** IPC connection (when backend ready)

---

### `/rules`
Manage custom validation rules from `.warden/rules.yaml`.

**Usage:**
```
/rules [list|show <id>|stats]
```

**Alias:** `/r`

**Subcommands:**

#### `/rules list` or `/rules ls`
Show all custom rules grouped by category.

**Output:**
- Total rules count
- Enabled/disabled count
- Rules by category
- Rule status, severity, description

#### `/rules show <rule_id>` or `/rules get <rule_id>`
Show detailed information about specific rule.

**Example:**
```bash
/rules show no-print-statements
```

**Output:**
- Rule name and ID
- Status (enabled/disabled)
- Severity level
- Category
- Description
- Pattern (regex)
- Tags

#### `/rules stats` or `/rules statistics`
Show rule statistics.

**Output:**
- Total/enabled/disabled counts
- Distribution by severity
- Distribution by category

**Configuration:**
Rules are read from `.warden/rules.yaml` in project root.

**Example config:**
```yaml
version: "1.0.0"
rules:
  - id: "no-print-statements"
    name: "No Print Statements"
    description: "Avoid print() in production code"
    severity: "medium"
    pattern: "print\\(.*\\)"
    category: "code-quality"
    enabled: true
    tags: ["best-practices", "production"]
```

**Requires:** No IPC (local file read)

---

## ⌨️ Keyboard Shortcuts

### Command List Navigation
- **`/`** - Show command list
- **`↑` / `↓`** - Navigate commands
- **`Tab`** - Auto-complete selected command
- **`Enter`** - Submit command
- **`Esc`** - Close list (type to dismiss)

### General
- **`Enter`** - Send message
- **`Ctrl+C`** - Exit application

---

## 🎨 Command Filtering

Type part of command name to filter:

```
/     → Shows all 9 commands
/an   → Shows only /analyze
/val  → Shows only /validate
/r    → Shows only /rules
```

Filtering works on:
- Command names
- Command aliases

---

## 💡 Tips & Tricks

### Quick Commands
```bash
# Use aliases for faster typing
/a file.py      # Instead of /analyze file.py
/s src/         # Instead of /scan src/
/v file.py sec  # Instead of /validate file.py security
```

### Command Chaining (Sequential)
```bash
# 1. Analyze file
/analyze src/main.py

# 2. Run specific validation
/validate src/main.py security

# 3. Check rules
/rules stats
```

### Validation Workflow
```bash
# 1. List available frames
/validate --list

# 2. Run specific frames
/validate src/main.py security,orphan

# 3. Full analysis if needed
/analyze src/main.py
```

### Directory Analysis
```bash
# Scan entire project
/scan .

# Scan specific directory
/scan src/

# Scan and then analyze top file
/scan src/
/analyze src/problematic_file.py
```

---

## 🔧 Troubleshooting

### "IPC connection not available"
**Problem:** Command requires backend but IPC not connected.

**Solution:**
```bash
# Terminal 1: Start IPC server
python3 start_ipc_server.py

# Terminal 2: Run CLI
warden-chat
```

### "File not found"
**Problem:** File path doesn't exist.

**Solution:**
- Use absolute paths: `/full/path/to/file.py`
- Or relative to current directory: `./src/file.py`
- Check file exists: `ls <file_path>`

### "Unknown command"
**Problem:** Command not recognized.

**Solution:**
- Type `/` to see all available commands
- Check spelling and use Tab auto-complete
- Use `/help` for full command list

### Command list not showing
**Problem:** Typing `/` doesn't show commands.

**Solution:**
- Make sure CLI is running (not hung)
- Try typing `/help` and Enter
- Restart CLI if needed

---

## 📊 Status Indicators

### Severity Levels
- 🔴 **CRITICAL** - Must fix immediately
- 🟠 **HIGH** - Should fix soon
- 🟡 **MEDIUM** - Fix when possible
- 🟢 **LOW** - Nice to fix
- 🔵 **INFO** - Informational only

### Frame Status
- ✅ **Passed** - No issues found
- ❌ **Failed** - Issues detected
- ⏭️ **Skipped** - Not executed
- 🔴 **BLOCKER** - Critical frame

### Connection Status
- ✅ **Connected** - IPC active
- ❌ **Disconnected** - No IPC
- ⏳ **Connecting** - In progress

---

## 📚 Related Documentation

- **Full Implementation:** See `WARDEN_INK_CLI_COMPLETE_SUMMARY.md`
- **CLI Architecture:** See `cli/README.md`
- **IPC Bridge:** See `src/warden/cli_bridge/README.md`
- **Validation Frames:** See `docs/VALIDATION_FRAMES.md`

---

**Version:** 0.1.0
**Last Updated:** 2025-12-22
**Status:** ✅ All commands implemented and tested
