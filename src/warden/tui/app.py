"""
Warden TUI Main Application

Professional terminal UI for AI Code Guardian.
Features: Slash commands, chat interface, code analysis, real-time streaming.
"""

from pathlib import Path
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.widgets import Header, Footer, Input, Static
from textual.binding import Binding
from rich.markdown import Markdown

from .widgets import CommandPaletteScreen, FilePickerScreen
from .handlers import handle_chat_message, handle_slash_command

# Import real Warden components
try:
    from warden.core.pipeline.orchestrator import PipelineOrchestrator
    from warden.config.discovery import discover_config
    PIPELINE_AVAILABLE = True
except ImportError:
    PIPELINE_AVAILABLE = False


class WardenTUI(App):
    """
    Warden - AI Code Guardian TUI

    Modern terminal interface with:
    - Slash command system
    - Interactive chat
    - Real-time code analysis
    - Session management
    """

    CSS_PATH = "warden.tcss"

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", show=True),
        Binding("ctrl+c", "quit", "Quit", show=False),
        Binding("ctrl+p", "command_palette", "Commands", show=True, key_display="^P"),
        Binding("/", "command_palette", "Commands", show=False),
        Binding("ctrl+l", "clear_chat", "Clear", show=True),
        Binding("ctrl+s", "save_session", "Save", show=True),
    ]

    TITLE = "🛡️  Warden - AI Code Guardian"
    SUB_TITLE = "Your production code quality enforcer"

    def __init__(self, project_root: Path = None, config_path: str = None):
        """Initialize Warden TUI."""
        super().__init__()
        self.project_root = project_root or Path.cwd()
        self.session_id = None
        self.llm_available = False
        self.pipeline_config = None
        self.orchestrator = None
        self.active_config_name = "quick-scan"

        # Initialize pipeline with config discovery (None = auto-discover)
        self._load_pipeline_config(config_path)

    def compose(self) -> ComposeResult:
        """Create child widgets."""
        yield Header(show_clock=True)

        # Main container with chat area
        with Container(id="main-container"):
            # Session info bar
            yield Static(self._get_session_info(), id="session-info")

            # Chat messages area - use VerticalScroll for proper scrolling
            with VerticalScroll(id="chat-area"):
                yield Static(
                    "Welcome to Warden\n\n"
                    "Type / to see commands or just ask a question",
                    id="welcome-message",
                    classes="system-message"
                )

            # Input area with prompt
            with Horizontal(id="input-container"):
                yield Static("›", id="prompt")
                yield Input(
                    placeholder="Ask a question • / for commands • @ for files",
                    id="chat-input"
                )

        yield Footer()

    def _load_pipeline_config(self, config_name: str) -> None:
        """Load pipeline configuration using discovery system."""
        if not PIPELINE_AVAILABLE:
            return

        try:
            from warden.config.discovery import discover_config, get_config_source

            # Discover config with hierarchy
            config = discover_config(
                start_path=self.project_root,
                template_name=config_name if config_name else None
            )

            if not config:
                import sys
                print(f"⚠️  No config found", file=sys.stderr)
                self.active_config_name = "none"
                self.orchestrator = None
                return

            # Create orchestrator with discovered config
            self.orchestrator = PipelineOrchestrator(config=config)

            # Set active config name based on source
            self.active_config_name = get_config_source(
                start_path=self.project_root,
                template_name=config_name if config_name else None
            )

        except Exception as e:
            # Log error but don't crash
            import sys
            print(f"⚠️  Pipeline loading error: {str(e)}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            self.active_config_name = "error"
            self.orchestrator = None

    def _get_session_info(self) -> str:
        """Get session info bar text."""
        pipeline_status = "⚙️ Full Pipeline" if self.orchestrator else "⚙️ No Pipeline"
        info_parts = [
            f"📁 {self.project_root.name}",
            pipeline_status,
            f"📋 {self.active_config_name}",
        ]

        if self.session_id:
            info_parts.append(f"🔖 Session: {self.session_id[:8]}")

        return " | ".join(info_parts)

    def on_mount(self) -> None:
        """Called when app is mounted."""
        # Focus on input
        self.query_one("#chat-input", Input).focus()

        # Initialize session
        self._initialize_session()

    def _initialize_session(self) -> None:
        """Initialize Warden session."""
        import uuid
        self.session_id = str(uuid.uuid4())

        # Check LLM availability
        try:
            import os
            if os.getenv("AZURE_OPENAI_API_KEY"):
                self.llm_available = True
        except Exception:
            pass

        # Update session info
        session_info = self.query_one("#session-info", Static)
        session_info.update(self._get_session_info())

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle input changes - open command palette on / or file picker on @."""
        if event.value == "/":
            # Clear the input
            event.input.value = ""
            # Open command palette
            self.action_command_palette()
        elif event.value.endswith("@"):
            # Trigger file picker
            self._show_file_picker(event.input)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle input submission."""
        user_input = event.value.strip()

        if not user_input:
            return

        # Clear input
        event.input.value = ""

        # Add user message to chat
        self._add_message(f"**You:** {user_input}", "user-message", markdown=True)

        # Check if it's a slash command
        if user_input.startswith("/"):
            await handle_slash_command(
                user_input,
                self,
                self.project_root,
                self.session_id,
                self.llm_available,
                self.orchestrator,
                self._add_message,
            )
        else:
            await handle_chat_message(user_input, self._add_message)

        # Keep focus on input after processing
        self.call_later(lambda: self.query_one("#chat-input", Input).focus())

    def _add_message(
        self, message: str, css_class: str = "message", markdown: bool = False
    ) -> None:
        """
        Add message to chat area.

        Args:
            message: Message text
            css_class: CSS class for styling
            markdown: Whether to render as markdown
        """
        chat_area = self.query_one("#chat-area", VerticalScroll)

        if markdown:
            # Render markdown for formatted messages
            message_widget = Static(Markdown(message), classes=css_class)
        else:
            message_widget = Static(message, classes=css_class)

        chat_area.mount(message_widget)

        # Scroll to bottom
        chat_area.scroll_end(animate=True)

    def action_command_palette(self) -> None:
        """Show command palette."""
        self.push_screen(CommandPaletteScreen())

    def _show_file_picker(self, input_widget: Input) -> None:
        """Show file picker and insert selected path."""
        def handle_selection(path: str | None) -> None:
            if path:
                # Get current input value and replace @ with selected path
                current = input_widget.value
                # Remove the @ that triggered the picker
                if current.endswith("@"):
                    current = current[:-1]
                # Insert the path
                input_widget.value = current + path + " "
                input_widget.focus()
                # Move cursor to end
                input_widget.cursor_position = len(input_widget.value)

        self.push_screen(FilePickerScreen(self.project_root), handle_selection)

    async def action_clear_chat(self) -> None:
        """Clear chat area."""
        chat_area = self.query_one("#chat-area", VerticalScroll)
        await chat_area.remove_children()

        # Add welcome message back
        chat_area.mount(
            Static(
                "Chat cleared. Ready for new conversation! 🛡️",
                classes="system-message"
            )
        )

        # Refocus input
        self.query_one("#chat-input", Input).focus()

    def action_save_session(self) -> None:
        """Save current session."""
        self._add_message("💾 Session saved!", "system-message")
        # TODO: Implement session save


def run_tui(project_root: Path = None):
    """Run Warden TUI."""
    app = WardenTUI(project_root=project_root)
    app.run()


if __name__ == "__main__":
    run_tui()
