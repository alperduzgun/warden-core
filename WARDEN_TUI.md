# Warden TUI - Modern Terminal Interface

Professional Terminal User Interface for Warden AI Code Guardian, built with Textual framework.

## 🎯 Overview

Warden TUI provides a modern, interactive terminal experience similar to QwenCode, with a clean interface, command palette, and real-time chat capabilities.

## 🚀 Quick Start

### Installation

```bash
# Install Warden with dependencies
pip install -e .

# Or install Textual separately
pip install textual textual-dev
```

### Launch

```bash
# Start Warden TUI (default when no args)
warden

# Or explicitly
warden chat

# Or run directly
python src/warden/tui/app.py
```

## 🎨 Interface

```
┌────────────────────────────────────────────────────────┐
│ 🛡️  Warden - AI Code Guardian        23:09:15         │ Header
├────────────────────────────────────────────────────────┤
│ 📁 warden-core | ⚡ LLM: AST-only | 🔖 Session: a1b2  │ Info Bar
├────────────────────────────────────────────────────────┤
│                                                        │
│  Welcome to Warden! 🛡️                                 │
│  Type / for commands or chat naturally                │
│                                                        │
│  You: /help                                            │
│  Warden: Here are available commands...                │
│                                                        │ Chat Area
│                                                        │
│                                                        │
│                                                        │
├────────────────────────────────────────────────────────┤
│ warden> / for commands or chat naturally...           │ Input
├────────────────────────────────────────────────────────┤
│ ^q Quit  / Commands  ^l Clear  ^s Save                │ Footer
└────────────────────────────────────────────────────────┘
```

## ⌨️ Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+Q` | Quit Warden |
| `Ctrl+C` | Quit Warden |
| `/` | Open Command Palette |
| `Ctrl+L` | Clear chat history |
| `Ctrl+S` | Save session |
| `Escape` | Close popups/modals |
| `Enter` | Send message/Execute command |

## 📋 Slash Commands

### Analysis Commands

#### `/analyze` (aliases: `/a`, `/check`)
Analyze a code file for issues and quality metrics.

```
/analyze main.py
/analyze src/utils.py --llm
/a app.py
```

#### `/scan` (alias: `/s`)
Scan entire project or directory.

```
/scan
/scan src/
/s --recursive
```

#### `/validate` (alias: `/v`)
Run validation frames on code.

```
/validate file.py
/v --all
```

### Fixing Commands

#### `/fix` (aliases: `/f`, `/repair`)
Auto-fix issues in code.

```
/fix main.py
/f --dry-run
/repair src/app.py
```

### Utility Commands

#### `/help` (aliases: `/h`, `/?`)
Show available commands and usage.

```
/help
/h
/?
```

#### `/status` (alias: `/info`)
Show current session status and configuration.

```
/status
/info
```

#### `/clear` (alias: `/cls`)
Clear chat history.

```
/clear
/cls
```

#### `/config` (aliases: `/cfg`, `/settings`)
View or modify Warden configuration.

```
/config show
/config set verbose=true
/cfg
```

#### `/quit` (aliases: `/exit`, `/q`)
Exit Warden TUI.

```
/quit
/exit
/q
```

## 💬 Chat Interface

### Natural Language

You can chat naturally without slash commands:

```
You: analyze this file for security issues
Warden: 🔍 Analyzing for security vulnerabilities...

You: scan the entire project
Warden: 🔍 Scanning all files in warden-core...

You: what issues did you find?
Warden: Found 3 issues: ...
```

### Message Types

- **User messages**: Blue left border
- **Assistant messages**: Green left border
- **System messages**: Yellow left border, italic
- **Error messages**: Red left border, red background

## 🎭 Command Palette

Press `/` to open the command palette - a searchable list of all available commands.

Features:
- ⌨️ Categorized commands (analysis, fixing, utilities, config)
- 🏷️ Shows command aliases
- 📖 Displays descriptions
- ⬆️⬇️ Navigate with arrow keys
- `Enter` to select
- `Escape` to close

## 🎨 Customization

### CSS Styling

Warden uses Textual CSS (TCSS) for styling. Edit `src/warden/tui/warden.tcss`:

```css
/* Example: Change session info bar color */
#session-info {
    background: $primary;  /* Change to your color */
}

/* Example: Change message style */
.user-message {
    border-left: thick $accent;
    color: $text;
}
```

### Color Themes

Textual provides built-in themes:
- Default (dark)
- Light
- Nord
- Monokai
- Gruvbox

## 🔧 Architecture

### File Structure

```
src/warden/tui/
├── __init__.py          # Package exports
├── app.py               # Main TUI application (WardenTUI class)
├── widgets.py           # Custom widgets (CommandPalette, MessageWidget)
└── warden.tcss          # Textual CSS styling
```

### Key Components

**WardenTUI (app.py)**
- Main application class
- Event handlers (input, mount, etc.)
- Command routing
- Session management

**CommandPaletteScreen (widgets.py)**
- Modal screen for command list
- Searchable, categorized commands
- Keyboard navigation

**MessageWidget (widgets.py)**
- Chat message display
- Type-based styling
- Rich text support

## 🔌 Integration

### Adding New Commands

1. Add to command list in `widgets.py`:

```python
{
    "name": "/mycommand",
    "aliases": ["/mc"],
    "description": "Does something awesome",
    "category": "utilities"
}
```

2. Add handler in `app.py`:

```python
async def _handle_slash_command(self, command: str):
    # ...
    elif cmd in ["mycommand", "mc"]:
        self._add_message("Executing mycommand...", "system-message")
        # Your logic here
```

### LLM Integration

To enable LLM features, set environment variable:

```bash
export AZURE_OPENAI_API_KEY="your-key"
export AZURE_OPENAI_ENDPOINT="your-endpoint"
```

## 🐛 Troubleshooting

### TUI doesn't start

```bash
# Check Textual installation
python -c "import textual; print(textual.__version__)"

# Reinstall if needed
pip install --upgrade textual textual-dev
```

### CSS errors

- Check `warden.tcss` syntax
- Textual CSS uses `$` for variables (e.g., `$primary`)
- No webkit-specific CSS (use Textual properties)

### Input not working

- Make sure terminal supports full input
- Try running in a different terminal
- Check if `TERM` environment variable is set

## 📊 Development

### Live Development

Use Textual dev mode for live reload:

```bash
# Install textual dev tools
pip install textual-dev

# Run with live reload
textual run --dev src/warden/tui/app.py
```

### Debugging

```bash
# Enable Textual console for debugging
textual console

# In another terminal, run Warden
warden
```

### Testing

```bash
# Unit tests
pytest tests/test_tui.py

# Manual testing
python src/warden/tui/app.py
```

## 🎯 Roadmap

- [ ] LLM streaming responses
- [ ] Code syntax highlighting in messages
- [ ] Session save/load
- [ ] Multiple theme support
- [ ] File browser widget
- [ ] Code diff viewer
- [ ] Multi-tab support
- [ ] Mouse support
- [ ] Export chat history

## 📚 Resources

- [Textual Documentation](https://textual.textualize.io/)
- [Textual Tutorial](https://textual.textualize.io/tutorial/)
- [Textual CSS Reference](https://textual.textualize.io/guide/CSS/)
- [Textual Widgets](https://textual.textualize.io/widgets/)

## 🆚 vs QwenCode

| Feature | QwenCode | Warden TUI |
|---------|----------|------------|
| **Technology** | TypeScript + Ink (React) | Python + Textual |
| **UI Framework** | Ink | Textual |
| **Styling** | CSS-in-JS | Textual CSS |
| **Command Palette** | ✅ | ✅ |
| **Keyboard Shortcuts** | ✅ | ✅ |
| **Chat Interface** | ✅ | ✅ |
| **Session Management** | ✅ | ✅ |
| **Python Native** | ❌ | ✅ |
| **Lighter** | ❌ | ✅ |
| **Faster Startup** | ❌ | ✅ |

---

**Warden TUI** - Professional terminal interface for AI Code Guardian 🛡️✨
