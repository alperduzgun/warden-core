"""Help command handler for Warden TUI."""

from typing import Callable


def handle_help_command(
    add_message: Callable[[str, str, bool], None],
) -> None:
    """
    Handle /help command.

    Args:
        add_message: Function to add messages to chat
    """
    help_text = """
# 📖 Warden Commands

## 🔍 Analysis Commands
- `/analyze <file>` or `/a <file>` - Analyze a code file
- `/scan [path]` or `/s [path]` - Scan project or directory
- `/validate <file>` or `/v <file>` - Run validation frames

## 🔧 Fixing Commands
- `/fix <file>` or `/f <file>` - Auto-fix issues in code

## ⚙️  Utility Commands
- `/help` or `/h` or `/?` - Show this help
- `/status` or `/info` - Show session status
- `/clear` or `/cls` - Clear chat history
- `/quit` or `/exit` or `/q` - Exit Warden

## ⌨️  Keyboard Shortcuts
- `Ctrl+P` or `/` - **Open command palette** (shows all commands)
- `Ctrl+Q` - Quit Warden
- `Ctrl+L` - Clear chat
- `Ctrl+S` - Save session

## 💡 Pro Tips
- **Command Palette**: Press `Ctrl+P` or type `/` to see all commands in a searchable list
- **Chat Naturally**: You can also chat without slash commands (e.g., "analyze my code")
- **Aliases**: Most commands have shortcuts (e.g., `/a` = `/analyze`, `/s` = `/scan`)
- **Markdown Support**: Messages support rich formatting with **bold**, `code`, and more
    """
    add_message(help_text.strip(), "system-message", True)
