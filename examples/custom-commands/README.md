# Custom Command Examples

This directory contains example TOML command definitions for Warden CLI.

## Installation

Copy these files to your commands directory:

```bash
# User-level (available in all projects)
cp -r examples/custom-commands/* ~/.warden/commands/

# Project-level (available in current project only)
cp -r examples/custom-commands/* .warden/commands/
```

## Available Commands

### `/code-review <file>`

Comprehensive code review with security and performance analysis.

**Example:**
```
/code-review src/warden/cli/main.py
```

**Features:**
- Code quality assessment
- Security vulnerability detection
- Performance optimization suggestions
- Best practices recommendations
- Documentation improvements

### `/git:summary`

Summarize recent git activity and development status.

**Example:**
```
/git:summary
```

**Features:**
- Recent commit summary
- Active development areas
- Potential merge conflicts
- Next steps recommendations

### `/search:grep-code <pattern>`

Search code for pattern and provide analysis.

**Example:**
```
/search:grep-code "TODO"
/search:grep-code "def main"
```

**Features:**
- Pattern location summary
- Common usage patterns
- Potential issues detection
- Refactoring suggestions

## Creating Your Own Commands

1. Create a `.toml` file in your commands directory
2. Define the `prompt` and optional `description`
3. Use template variables:
   - `{{args}}` - Command arguments
   - `@{path}` - File injection
   - `!{command}` - Shell execution

### Example Template

```toml
prompt = """
Your prompt here using:
- Arguments: {{args}}
- File content: @{{{args}}}
- Command output: !{ls -la}
"""

description = "Brief description of what this command does"
```

## Template Variables

### `{{args}}`

Replaced with command arguments:

```toml
prompt = "Analyze {{args}} for issues"
```

Usage: `/analyze src/main.py` → "Analyze src/main.py for issues"

### `@{path}`

Inject file contents:

```toml
prompt = """
Review this code:
@{src/main.py}
"""
```

### `!{command}`

Execute shell command and inject output:

```toml
prompt = """
Git status:
!{git status}
"""
```

## Nested Commands

Use directories to create namespaced commands:

```
.warden/commands/
├── git/
│   ├── summary.toml    → /git:summary
│   ├── log.toml        → /git:log
│   └── diff.toml       → /git:diff
└── code/
    ├── review.toml     → /code:review
    └── analyze.toml    → /code:analyze
```

## Security

- File paths are validated against project root
- Dangerous shell commands require confirmation
- Template variables are properly escaped
- Commands run in project directory only

## Best Practices

1. **Use descriptive names**: `code:review` instead of `cr`
2. **Add descriptions**: Help users understand the command
3. **Validate arguments**: Check that `{{args}}` is provided
4. **Test shell commands**: Ensure they work cross-platform
5. **Document examples**: Include usage examples

## More Information

See `docs/COMMAND_SYSTEM.md` for comprehensive documentation.
