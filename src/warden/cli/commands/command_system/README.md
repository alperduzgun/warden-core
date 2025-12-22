# Command System

A flexible command system for Warden CLI inspired by Qwen Code.

## Features

- **Slash Commands** (`/`) - Built-in commands for common operations
- **At Commands** (`@`) - File and directory content injection
- **Bang Commands** (`!`) - Shell command execution with safety checks
- **Custom Commands** - TOML-based extensible commands with template variables

## Quick Start

### Using CommandService

```python
from pathlib import Path
from warden.cli.commands.command_system import CommandService

# Create service with default loaders
project_root = Path.cwd()
service = await CommandService.create_default(project_root)

# Get available commands
commands = service.get_commands()
for cmd in commands:
    print(f"{cmd.name}: {cmd.description}")

# Execute a command
help_cmd = service.get_command("help")
if help_cmd:
    await help_cmd.action(context, "")
```

### Creating Custom Commands

Create a TOML file in `~/.warden/commands/`:

```toml
# ~/.warden/commands/analyze.toml
prompt = """
Analyze the code in {{args}} and provide:
1. Code quality assessment
2. Security vulnerabilities
3. Performance suggestions
"""
description = "Comprehensive code analysis"
```

Usage: `/analyze src/main.py`

## Architecture

### Core Components

- **`types.py`** - Type definitions and protocols
- **`command_service.py`** - Command orchestration and loading
- **`slash_commands.py`** - Built-in slash command handlers
- **`at_commands.py`** - File injection handlers
- **`bang_commands.py`** - Shell execution handlers
- **`file_command_loader.py`** - TOML command loader

### Processors

- **`processors/argument_processor.py`** - `{{args}}` expansion
- **`processors/at_file_processor.py`** - `@{path}` file injection
- **`processors/shell_processor.py`** - `!{command}` shell execution

## Command Types

### Built-in Commands

Loaded by `BuiltinCommandLoader`:

- `/help` - Show help
- `/analyze <path>` - Run analysis
- `/scan <path>` - Scan infrastructure
- `/config` - Show configuration
- `/status` - Show status
- `/clear` - Clear chat
- `/quit` - Exit

### File Commands

Loaded from TOML files by `FileCommandLoader`:

- User commands: `~/.warden/commands/*.toml`
- Project commands: `<project>/.warden/commands/*.toml`

### Extension Commands

Future: Loaded from installed extensions.

## Template Variables

### `{{args}}`

Replaced with command arguments:

```toml
prompt = "Analyze {{args}} for issues"
```

### `@{path}`

Inject file contents:

```toml
prompt = """
Review this code:
@{{{args}}}
"""
```

### `!{command}`

Execute shell command:

```toml
prompt = """
Git status:
!{git status}
"""
```

## Security

### File Access

- Paths validated against project root
- Respects `.gitignore` and `.wardenignore`
- Binary files skipped automatically
- Symbolic links followed with caution

### Shell Execution

- Dangerous commands require confirmation
- Commands: `rm`, `sudo`, `chmod`, `kill`, etc.
- Patterns: `-rf`, `--force`, `&&`, `;`, `|`
- Runs in project directory only

### Template Processing Order

1. **File injection** (`@{path}`) - Security first
2. **Shell/Arguments** (`!{cmd}`, `{{args}`)
3. **Default arguments** - Append if no `{{args}}`

This prevents shell commands from generating malicious file paths.

## API Reference

### CommandService

```python
class CommandService:
    @classmethod
    async def create(loaders: list[ICommandLoader]) -> CommandService

    @classmethod
    async def create_default(project_root: Path) -> CommandService

    def get_commands() -> list[Command]

    def get_command(name: str) -> Command | None

    def find_commands(prefix: str) -> list[Command]
```

### Command Protocol

```python
class Command(Protocol):
    name: str
    description: str
    kind: CommandKind
    extension_name: str | None

    async def action(context: CommandContext, args: str) -> CommandActionReturn
```

### CommandContext

```python
@dataclass
class CommandContext:
    app: Any  # Textual App
    project_root: Path
    session_id: str | None
    llm_available: bool
    orchestrator: Any | None
    add_message: Callable[[str, str, bool], None]
    invocation: CommandInvocation | None
```

### Return Types

```python
@dataclass
class SubmitPromptReturn:
    type: str = "submit_prompt"
    content: list[PromptContent]

@dataclass
class ConfirmShellReturn:
    type: str = "confirm_shell_commands"
    commands_to_confirm: list[str]
    original_invocation: CommandInvocation
```

## Testing

Run tests:

```bash
pytest tests/cli/commands/
```

Test coverage:

```bash
pytest tests/cli/commands/ --cov=src/warden/cli/commands/command_system --cov-report=html
```

## Examples

See `docs/COMMAND_SYSTEM.md` for comprehensive examples and usage patterns.

## Contributing

When adding new command types:

1. Create loader implementing `ICommandLoader`
2. Add to `CommandService.create_default()`
3. Add tests in `tests/cli/commands/`
4. Document in `docs/COMMAND_SYSTEM.md`

When adding new processors:

1. Implement `IPromptProcessor` protocol
2. Add to `FileCommandLoader._create_command()`
3. Add tests for template expansion
4. Update documentation

## License

Part of the Warden project.
