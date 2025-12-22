# Warden Command System

The Warden command system provides a flexible and extensible way to interact with the CLI, inspired by Qwen Code's command architecture.

## Overview

The command system supports three types of commands:

1. **Slash Commands (`/`)** - Built-in commands for common operations
2. **At Commands (`@`)** - File and directory injection
3. **Bang Commands (`!`)** - Shell command execution
4. **Custom Commands** - TOML-based extensible commands

## Slash Commands

Slash commands provide built-in functionality for interacting with Warden.

### Available Commands

#### Analysis & Scanning
- `/analyze <path>` or `/a <path>` - Run pipeline analysis on a file or directory
- `/scan <path>` or `/s <path>` - Scan infrastructure for vulnerabilities
- `/rules` or `/r` - Manage validation rules

#### Information
- `/help` or `/h` or `/?` - Show help message with all available commands
- `/config` - Display current configuration
- `/status` or `/info` - Show system status

#### Navigation
- `/clear` or `/cls` - Clear chat history
- `/quit` or `/exit` or `/q` - Exit the application

### Usage Examples

```
/help
/analyze src/main.py
/scan infrastructure/
/config
/clear
```

## At Commands

At commands allow you to inject file contents into your prompts, making it easy to provide context to the AI.

### Syntax

```
@<path>
```

### Features

- **Single File**: `@src/main.py` - Inject a single file
- **Directory**: `@src/` - Recursively read all files in a directory
- **Gitignore Support**: Respects `.gitignore` and `.wardenignore` patterns
- **Syntax Highlighting**: Automatically detects language from file extension
- **Binary File Filtering**: Skips binary files automatically

### Security

- Paths must be within the project root
- Respects ignore patterns from `.gitignore` and `.wardenignore`
- Default ignore patterns for common directories (`node_modules`, `.git`, etc.)

### Usage Examples

```
@README.md
@src/warden/cli/main.py
@src/
```

### Supported Languages

Python, JavaScript, TypeScript, Java, C/C++, Go, Rust, Ruby, PHP, Swift, Kotlin, Scala, Shell scripts, YAML, JSON, TOML, XML, HTML, CSS, Markdown, SQL, Terraform, and more.

## Bang Commands

Bang commands allow you to execute shell commands and inject their output into the chat.

### Syntax

```
!<command>
```

### Features

- **Command Execution**: Run any shell command in the project directory
- **Safety Approval**: Dangerous commands require user confirmation
- **Output Streaming**: Real-time command output display
- **Error Handling**: Captures both stdout and stderr
- **Exit Code Tracking**: Shows command success/failure

### Dangerous Commands

The following commands automatically require confirmation:

- File operations: `rm`, `rmdir`, `del`, `mv`, `chmod`, `chown`
- System operations: `shutdown`, `reboot`, `kill`, `sudo`
- Disk operations: `dd`, `mkfs`, `fdisk`, `format`
- Commands with: `--force`, `-rf`, `&&`, `;`, `|`, redirects

### Usage Examples

```
!ls -la
!git status
!pytest tests/
!npm test
```

### Dangerous Command Example

```
!rm -rf temp/
```

This will trigger a confirmation dialog before execution.

## Custom Commands (TOML)

Create your own commands using TOML files for frequently used operations.

### Directory Structure

```
~/.warden/commands/          # User-level commands
<project>/.warden/commands/  # Project-level commands
```

### TOML Format

```toml
prompt = "Your prompt template here"
description = "Description shown in help"
```

### Template Variables

#### `{{args}}` - Command Arguments

Replace `{{args}}` with the arguments passed to the command.

```toml
prompt = "Analyze the code in {{args}} and provide suggestions"
description = "Analyze code with suggestions"
```

Usage: `/analyze:suggest src/main.py`

#### `@{path}` - File Injection

Inject file contents into the prompt.

```toml
prompt = """
Review this code:
@{{{args}}}

Provide a detailed code review.
"""
description = "Code review assistant"
```

Usage: `/review src/main.py`

#### `!{command}` - Shell Command Injection

Execute shell commands and inject output.

```toml
prompt = """
Here are the recent git commits:
!{git log --oneline -10}

Summarize the changes.
"""
description = "Summarize recent commits"
```

Usage: `/git:summary`

### Nested Commands

Use directories to create namespaced commands:

```
.warden/commands/
├── git/
│   ├── log.toml
│   ├── status.toml
│   └── diff.toml
└── code/
    ├── review.toml
    └── analyze.toml
```

This creates commands like: `/git:log`, `/git:status`, `/code:review`

### Complete Example

**File: `~/.warden/commands/fs/grep-code.toml`**

```toml
prompt = """
Please summarize the findings for the pattern `{{args}}`.

Search Results:
!{grep -r {{args}} .}
"""
description = "Search code and summarize findings"
```

Usage: `/fs:grep-code "TODO"`

### Command Priority

Commands are loaded in order:

1. User commands (`~/.warden/commands/`)
2. Project commands (`<project>/.warden/commands/`)
3. Extension commands (if any)

Later commands override earlier ones with the same name.

## Architecture

### Components

```
CommandService
├── BuiltinCommandLoader      # Loads slash commands
├── FileCommandLoader          # Loads TOML commands
└── (Future) ExtensionLoader   # Loads extension commands

Processors
├── ArgumentProcessor          # Handles {{args}}
├── AtFileProcessor           # Handles @{path}
└── ShellProcessor            # Handles !{command}
```

### Command Execution Flow

```
Input → Parse → Route → Process → Execute
         │       │        │         │
         │       │        │         └─→ Action
         │       │        └─→ Template Expansion
         │       └─→ Command Lookup
         └─→ Detect Command Type
```

### Template Processing Order

For TOML commands, templates are processed in this order:

1. **File Injection** (`@{path}`) - Security first
2. **Shell/Arguments** (`!{cmd}`, `{{args}}`) - After files loaded
3. **Default Arguments** - Append if no `{{args}}`

This order ensures shell commands can't dynamically generate malicious file paths.

## Integration

### Using CommandService

```python
from pathlib import Path
from warden.cli.commands.command_system import CommandService, CommandContext

# Create service
project_root = Path("/path/to/project")
service = await CommandService.create_default(project_root)

# Get all commands
commands = service.get_commands()

# Find a command
help_cmd = service.get_command("help")

# Autocomplete
suggestions = service.find_commands("ana")  # Returns ["analyze"]

# Execute command
context = CommandContext(
    app=app,
    project_root=project_root,
    session_id=session_id,
    llm_available=True,
    orchestrator=orchestrator,
    add_message=add_message_fn,
)

result = await help_cmd.action(context, "")
```

### Command Context

All commands receive a `CommandContext` with:

- `app`: Textual App instance
- `project_root`: Project root directory
- `session_id`: Current session ID
- `llm_available`: Whether LLM is available
- `orchestrator`: Pipeline orchestrator instance
- `add_message`: Function to add messages to chat
- `invocation`: Details about how command was invoked

### Command Return Types

Commands can return:

- `SubmitPromptReturn` - Submit content to chat/LLM
- `ConfirmShellReturn` - Request shell command confirmation
- `None` - No return value (command handled internally)

## Security Considerations

### File Access

- All file paths are validated against project root
- Respects `.gitignore` and `.wardenignore`
- Binary files are automatically skipped
- Symbolic links are followed with caution

### Shell Execution

- Dangerous commands require explicit confirmation
- Commands run in project directory only
- No environment variable expansion by default
- Output is sanitized before display

### TOML Commands

- File injection happens before shell execution
- Template variables are escaped appropriately
- Command conflicts are handled safely
- Extension commands are sandboxed

## Best Practices

### Creating Custom Commands

1. **Use Descriptive Names**: `code:review` instead of `cr`
2. **Add Descriptions**: Help users understand what the command does
3. **Validate Arguments**: Use `{{args}}` thoughtfully
4. **Test Shell Commands**: Ensure they work in different environments
5. **Document Examples**: Include usage examples in descriptions

### File Injection

1. **Limit Scope**: Inject only necessary files
2. **Use Specific Paths**: `@src/main.py` instead of `@src/`
3. **Check File Sizes**: Large directories may be slow
4. **Respect Gitignore**: Don't inject generated files

### Shell Commands

1. **Prefer Safe Commands**: Use read-only commands when possible
2. **Handle Errors**: Check exit codes and stderr
3. **Limit Output**: Use filters to reduce output size
4. **Document Risks**: Warn users about dangerous operations

## Troubleshooting

### Command Not Found

- Check command name spelling
- Verify TOML file is in correct directory
- Use `/help` to see all available commands
- Check for syntax errors in TOML

### File Injection Failed

- Verify file exists and is readable
- Check path is relative to project root
- Ensure file isn't in `.gitignore`
- Check file isn't binary

### Shell Command Blocked

- Review dangerous command list
- Approve command when prompted
- Check command syntax
- Verify command exists on system

## Examples

### Daily Workflow Commands

**File: `~/.warden/commands/daily/standup.toml`**

```toml
prompt = """
Generate a standup report based on:

Recent Commits:
!{git log --since=yesterday --author="$(git config user.name)" --oneline}

Modified Files:
!{git diff --name-only HEAD~5}
"""
description = "Generate daily standup report"
```

**File: `~/.warden/commands/daily/review-pr.toml`**

```toml
prompt = """
Review the changes in this pull request:

Diff:
!{git diff {{args}}}

Please provide:
1. Code quality assessment
2. Potential bugs
3. Suggestions for improvement
"""
description = "Review pull request changes"
```

Usage: `/daily:review-pr origin/main..feature-branch`

## Future Enhancements

- Extension system for third-party commands
- Command aliases and shortcuts
- Command history and favorites
- Interactive command builder
- Command composition and chaining
- MCP (Model Context Protocol) integration
