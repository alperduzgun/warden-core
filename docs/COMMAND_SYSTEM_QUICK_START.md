# Command System Quick Start Guide

## Installation

The command system is built into Warden CLI. No additional installation required.

## Basic Commands

### Get Help

```
/help
```

Shows all available commands with descriptions.

### Run Analysis

```
/analyze src/main.py
/analyze src/
```

Run pipeline analysis on files or directories.

### Scan Infrastructure

```
/scan infrastructure/
```

Scan infrastructure for vulnerabilities.

### View Configuration

```
/config
```

Display current Warden configuration.

### Check Status

```
/status
```

Show system status and session information.

## File Injection

### Single File

```
@README.md
@src/warden/cli/main.py
```

Inject file content into your prompt.

### Directory

```
@src/
@tests/
```

Inject all files in a directory (respects .gitignore).

### Use in Prompt

```
Review this code: @src/main.py
```

Combine with natural language for context-aware prompts.

## Shell Execution

### Safe Commands

```
!ls -la
!git status
!pytest tests/
```

Execute shell commands and see output immediately.

### Dangerous Commands

```
!rm temp.txt
!sudo systemctl restart service
```

These require confirmation before execution.

## Custom Commands

### Create Your First Command

1. Create directory:
   ```bash
   mkdir -p ~/.warden/commands
   ```

2. Create file `~/.warden/commands/hello.toml`:
   ```toml
   prompt = "Say hello to {{args}}"
   description = "Greet someone"
   ```

3. Use it:
   ```
   /hello World
   ```

### File Review Command

Create `~/.warden/commands/review.toml`:

```toml
prompt = """
Please review this code:
@{{{args}}}

Provide:
1. Code quality
2. Security issues
3. Best practices
"""
description = "Comprehensive code review"
```

Usage:
```
/review src/main.py
```

### Git Summary Command

Create `~/.warden/commands/git/status.toml`:

```toml
prompt = """
Git Status:
!{git status}

Recent Commits:
!{git log --oneline -5}

Summarize the current state.
"""
description = "Git repository summary"
```

Usage:
```
/git:status
```

## Template Variables

### `{{args}}` - Arguments

```toml
prompt = "Analyze {{args}} for bugs"
```

Usage: `/analyze src/main.py` → "Analyze src/main.py for bugs"

### `@{path}` - File Content

```toml
prompt = "Review: @{{{args}}}"
```

Injects the file content specified in args.

### `!{command}` - Shell Output

```toml
prompt = "Files: !{ls -la}"
```

Executes command and injects output.

## Common Patterns

### Code Analysis

```toml
prompt = """
Analyze this code:
@{{{args}}}

Find:
- Bugs
- Security issues
- Performance problems
"""
description = "Code analysis"
```

### Search and Summarize

```toml
prompt = """
Search results for {{args}}:
!{grep -rn "{{args}}" src/}

Summarize findings.
"""
description = "Search code"
```

### Multi-File Review

```toml
prompt = """
Review these files:
@{src/main.py}
@{src/utils.py}

Check compatibility.
"""
description = "Multi-file review"
```

## Tips

### Security

- Commands run in project directory only
- Paths validated against project root
- Dangerous commands require confirmation
- Binary files automatically skipped

### Organization

Use directories for namespaces:

```
~/.warden/commands/
├── git/
│   ├── status.toml    → /git:status
│   ├── log.toml       → /git:log
│   └── diff.toml      → /git:diff
├── code/
│   ├── review.toml    → /code:review
│   └── analyze.toml   → /code:analyze
└── search/
    └── grep.toml      → /search:grep
```

### Best Practices

1. **Use descriptive names**: `code:review` not `cr`
2. **Add descriptions**: Help users understand
3. **Validate args**: Check `{{args}}` exists
4. **Test commands**: Ensure they work
5. **Document usage**: Add examples

## Autocomplete

Type `/` and start typing to see suggestions:

```
/ana[TAB]  → /analyze
/hel[TAB]  → /help
/git:[TAB] → shows git commands
```

## Troubleshooting

### Command not found

- Check spelling
- Use `/help` to see all commands
- Verify TOML file is in correct directory

### File not injected

- Check path is relative to project root
- Verify file exists
- Check .gitignore patterns
- Ensure file is not binary

### Shell command blocked

- Review dangerous commands list
- Approve when prompted
- Check command syntax
- Verify command exists

## Examples

See `examples/custom-commands/` for:
- `code-review.toml` - Comprehensive code review
- `git/summary.toml` - Git activity summary
- `search/grep-code.toml` - Code search and analysis

## More Information

- Full documentation: `docs/COMMAND_SYSTEM.md`
- API reference: `src/warden/cli/commands/command_system/README.md`
- Examples: `examples/custom-commands/README.md`

## Quick Reference

| Command | Description |
|---------|-------------|
| `/help` | Show help |
| `/analyze <path>` | Run analysis |
| `/scan <path>` | Scan infrastructure |
| `/config` | Show config |
| `/status` | Show status |
| `/rules` | Manage rules |
| `/clear` | Clear chat |
| `/quit` | Exit |
| `@<path>` | Inject file |
| `!<cmd>` | Execute shell |

## Get Started

1. Try built-in commands: `/help`
2. Inject a file: `@README.md`
3. Run a command: `!git status`
4. Create custom command: See examples above
5. Read full docs: `docs/COMMAND_SYSTEM.md`

Happy coding with Warden! 🛡️
