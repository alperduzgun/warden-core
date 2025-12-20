"""
Warden TUI Custom Widgets

Custom widgets for Warden terminal interface.
"""

from textual.app import ComposeResult
from textual.containers import Container, Vertical, VerticalScroll
from textual.widgets import Static, ListItem, ListView, Label, OptionList, DirectoryTree
from textual.widgets.option_list import Option
from textual.screen import ModalScreen
from rich.text import Text
from pathlib import Path


class CommandPaletteScreen(ModalScreen):
    """
    Command Palette Modal

    Displays all available slash commands in a searchable list.
    Similar to VS Code command palette.
    """

    CSS = """
    CommandPaletteScreen {
        align: center bottom;
        padding-bottom: 5;
    }

    #command-palette-container {
        width: 90;
        height: auto;
        max-height: 28;
        background: #161b22;
        border: thick #58a6ff;
        padding: 0;
    }

    #palette-title {
        dock: top;
        height: 3;
        background: #58a6ff;
        color: #0d1117;
        content-align: center middle;
        text-style: bold;
    }

    #command-list {
        height: auto;
        max-height: 22;
        background: #161b22;
        border: none;
        padding: 1;
    }

    #command-list:focus {
        background: #0d1117;
    }
    """

    BINDINGS = [
        ("escape", "dismiss", "Close"),
        ("enter", "select", "Select"),
    ]

    def __init__(self):
        super().__init__()
        self.commands = self._get_commands()

    def _get_commands(self) -> list:
        """Get all available commands"""
        return [
            {
                "name": "/help",
                "aliases": ["/h", "/?"],
                "description": "Show available commands and help",
                "category": "utilities"
            },
            {
                "name": "/analyze",
                "aliases": ["/a", "/check"],
                "description": "Analyze a code file for issues",
                "category": "analysis"
            },
            {
                "name": "/scan",
                "aliases": ["/s"],
                "description": "Scan entire project or directory",
                "category": "analysis"
            },
            {
                "name": "/fix",
                "aliases": ["/f", "/repair"],
                "description": "Auto-fix issues in code",
                "category": "fixing"
            },
            {
                "name": "/validate",
                "aliases": ["/v"],
                "description": "Run validation frames on code",
                "category": "validation"
            },
            {
                "name": "/status",
                "aliases": ["/info"],
                "description": "Show current session status",
                "category": "utilities"
            },
            {
                "name": "/clear",
                "aliases": ["/cls"],
                "description": "Clear chat history",
                "category": "utilities"
            },
            {
                "name": "/config",
                "aliases": ["/cfg", "/settings"],
                "description": "View or modify configuration",
                "category": "config"
            },
            {
                "name": "/quit",
                "aliases": ["/exit", "/q"],
                "description": "Exit Warden",
                "category": "utilities"
            },
        ]

    def compose(self) -> ComposeResult:
        """Create child widgets"""
        with Container(id="command-palette-container"):
            yield Static("⌨️  Command Palette • ↑↓ Navigate • Enter Select • Esc Close", id="palette-title")

            # Create options for OptionList
            options = []
            for cmd in self.commands:
                aliases_text = f" ({', '.join(cmd['aliases'])})" if cmd['aliases'] else ""
                category_emoji = self._get_category_emoji(cmd['category'])

                # Rich text formatting
                prompt = Text()
                prompt.append(f"{category_emoji} ", style="bold yellow")
                prompt.append(f"{cmd['name']}", style="bold cyan")
                prompt.append(f"{aliases_text}", style="dim")
                prompt.append(f"\n   {cmd['description']}", style="italic")

                options.append(Option(prompt, id=cmd['name']))

            yield OptionList(*options, id="command-list")

    def _get_category_emoji(self, category: str) -> str:
        """Get emoji for category"""
        emojis = {
            "analysis": "🔍",
            "fixing": "🔧",
            "validation": "✅",
            "utilities": "⚙️",
            "config": "⚙️",
        }
        return emojis.get(category, "📌")

    def on_mount(self) -> None:
        """Focus on list when mounted"""
        self.query_one("#command-list", OptionList).focus()

    def action_dismiss(self) -> None:
        """Close the command palette"""
        self.app.pop_screen()

    def action_select(self) -> None:
        """Select a command and execute it"""
        option_list = self.query_one("#command-list", OptionList)
        selected = option_list.highlighted

        if selected is not None:
            # Get the command ID (command name)
            command_id = option_list.get_option_at_index(selected).id
            if command_id:
                # Inject command into input
                self.app.pop_screen()
                # Send command to app's input
                chat_input = self.app.query_one("#chat-input")
                chat_input.value = command_id + " "
                chat_input.focus()
        else:
            self.app.pop_screen()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle option selection"""
        command_id = event.option.id
        if command_id:
            self.app.pop_screen()
            chat_input = self.app.query_one("#chat-input")
            chat_input.value = command_id + " "
            chat_input.focus()


class MessageWidget(Static):
    """
    Chat message widget

    Displays a single chat message with proper styling.
    """

    def __init__(self, message: str, message_type: str = "user", **kwargs):
        """
        Initialize message widget

        Args:
            message: Message text
            message_type: Type of message (user, assistant, system, error)
        """
        super().__init__(message, **kwargs)
        self.message_type = message_type
        self.add_class(f"{message_type}-message")


class FilePickerScreen(ModalScreen):
    """
    File/Folder Picker Modal

    Shows a directory tree for selecting files or folders.
    Triggered by @ in input.
    """

    CSS = """
    FilePickerScreen {
        align: center bottom;
        padding-bottom: 5;
    }

    #file-picker-container {
        width: 90;
        height: auto;
        max-height: 30;
        background: #161b22;
        border: thick #58a6ff;
        padding: 0;
    }

    #picker-title {
        dock: top;
        height: 3;
        background: #58a6ff;
        color: #0d1117;
        content-align: center middle;
        text-style: bold;
    }

    #file-tree {
        height: auto;
        max-height: 24;
        background: #161b22;
        padding: 1;
    }

    DirectoryTree {
        background: #161b22;
        scrollbar-background: #21262d;
        scrollbar-color: #58a6ff;
    }
    """

    BINDINGS = [
        ("escape", "dismiss", "Close"),
        ("enter", "select", "Select"),
    ]

    def __init__(self, root_path: Path):
        super().__init__()
        self.root_path = root_path
        self.selected_path = None

    def compose(self) -> ComposeResult:
        """Create child widgets"""
        with Container(id="file-picker-container"):
            yield Static("📁 File Picker • ↑↓ Navigate • Enter Select • Esc Close", id="picker-title")
            yield DirectoryTree(str(self.root_path), id="file-tree")

    def on_mount(self) -> None:
        """Focus on tree when mounted"""
        self.query_one("#file-tree", DirectoryTree).focus()

    def action_dismiss(self) -> None:
        """Close the file picker"""
        self.app.pop_screen()

    def action_select(self) -> None:
        """Select current file/folder"""
        tree = self.query_one("#file-tree", DirectoryTree)
        if tree.cursor_node:
            path = tree.cursor_node.data.path
            self.dismiss(str(path))
        else:
            self.dismiss(None)

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        """Handle file selection"""
        self.dismiss(str(event.path))

    def on_directory_tree_directory_selected(self, event: DirectoryTree.DirectorySelected) -> None:
        """Handle directory selection"""
        self.dismiss(str(event.path))


class SessionInfoBar(Static):
    """
    Session information bar

    Shows project info, LLM status, and session ID.
    """

    def __init__(self, project_name: str, llm_available: bool, session_id: str = None):
        """
        Initialize session info bar

        Args:
            project_name: Name of current project
            llm_available: Whether LLM is available
            session_id: Current session ID
        """
        self.project_name = project_name
        self.llm_available = llm_available
        self.session_id = session_id

        info_text = self._build_info_text()
        super().__init__(info_text, id="session-info")

    def _build_info_text(self) -> str:
        """Build session info text"""
        parts = [
            f"📁 {self.project_name}",
            "⚡ LLM: Ready" if self.llm_available else "⚡ LLM: AST-only",
        ]

        if self.session_id:
            parts.append(f"🔖 Session: {self.session_id[:8]}")

        return " | ".join(parts)

    def update_status(self, **kwargs):
        """Update session status"""
        if "llm_available" in kwargs:
            self.llm_available = kwargs["llm_available"]
        if "session_id" in kwargs:
            self.session_id = kwargs["session_id"]

        self.update(self._build_info_text())
