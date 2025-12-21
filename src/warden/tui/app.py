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

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not installed, environment variables should be set manually

# Import real Warden components
try:
    from warden.pipeline.application.orchestrator import PipelineOrchestrator
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
        """Load pipeline configuration from .warden/config.yaml and rules.yaml."""
        if not PIPELINE_AVAILABLE:
            return

        try:
            import yaml
            from warden.pipeline.domain.models import PipelineConfig as PipelineOrchestratorConfig
            from warden.rules.infrastructure.yaml_loader import RulesYAMLLoader
            import asyncio

            # Find config file
            config_file = self.project_root / ".warden" / "config.yaml"

            # ✅ NEW: Load custom rules from rules.yaml
            rules_file = self.project_root / ".warden" / "rules.yaml"
            global_rules = []
            frame_rules = {}

            if rules_file.exists():
                try:
                    # Load rules synchronously (TUI __init__ is sync)
                    loop = asyncio.new_event_loop()
                    rules_config = loop.run_until_complete(
                        RulesYAMLLoader.load_from_file(rules_file)
                    )
                    loop.close()

                    # Extract global rules (rules referenced in global_rules section)
                    rule_lookup = {rule.id: rule for rule in rules_config.rules if rule.enabled}
                    global_rules = [rule_lookup[rule_id] for rule_id in rules_config.global_rules if rule_id in rule_lookup]

                    # Get frame_rules from config (already parsed by loader)
                    frame_rules = rules_config.frame_rules

                    import sys
                    print(f"✅ Loaded {len(global_rules)} global rules + {len(frame_rules)} frame rules from {rules_file.name}", file=sys.stderr)

                except Exception as e:
                    import sys
                    print(f"⚠️  Failed to load custom rules: {e}", file=sys.stderr)

            if not config_file.exists():
                import sys
                print(f"⚠️  No config found at {config_file}, using default frames", file=sys.stderr)
                self.active_config_name = "default"

                # Use default frames when no config (with rules if loaded)
                frames = self._get_default_frames()
                config = PipelineOrchestratorConfig(
                    global_rules=global_rules,
                    frame_rules=frame_rules,
                ) if global_rules or frame_rules else None
                self.orchestrator = PipelineOrchestrator(frames=frames, config=config)
                return

            # Parse YAML directly (simple format - not visual builder format)
            with open(config_file) as f:
                config_data = yaml.safe_load(f)

            # Extract frame list and frame-specific configs
            frame_names = config_data.get('frames', [])
            frame_config = config_data.get('frame_config', {})

            if not frame_names:
                import sys
                print(f"⚠️  No frames in config, using defaults", file=sys.stderr)
                frames = self._get_default_frames()
                self.active_config_name = "default"
            else:
                # Load frames from list with their configs
                frames = self._load_frames_from_list(frame_names, frame_config)

                if not frames:
                    import sys
                    print(f"⚠️  Failed to load frames, using defaults", file=sys.stderr)
                    frames = self._get_default_frames()
                    self.active_config_name = "default"
                else:
                    self.active_config_name = config_data.get('name', 'project-config')

            # Create pipeline orchestrator config (domain model, not Panel model!) WITH custom rules
            settings = config_data.get('settings', {})
            pipeline_config = PipelineOrchestratorConfig(
                fail_fast=settings.get('fail_fast', True),
                timeout=settings.get('timeout', 300),
                frame_timeout=settings.get('timeout', 120),
                parallel_limit=4,
                global_rules=global_rules,  # ✅ NEW: Custom rules
                frame_rules=frame_rules,    # ✅ NEW: Frame-specific rules
            )

            # Create orchestrator with frames and config
            self.orchestrator = PipelineOrchestrator(frames=frames, config=pipeline_config)

        except Exception as e:
            # Log error but don't crash - use default frames
            import sys
            print(f"⚠️  Pipeline loading error: {str(e)}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            self.active_config_name = "error-fallback"

            # Fallback to default frames
            try:
                frames = self._get_default_frames()
                self.orchestrator = PipelineOrchestrator(frames=frames, config=None)
            except Exception:
                self.orchestrator = None

    def _get_default_frames(self) -> list:
        """Get default validation frames when no config is found."""
        from warden.validation.frames import (
            SecurityFrame,
            ChaosFrame,
            ArchitecturalConsistencyFrame,
        )

        return [
            SecurityFrame(),
            ChaosFrame(),
            ArchitecturalConsistencyFrame(),
        ]

    def _load_frames_from_list(self, frame_names: list, frame_config: dict = None) -> list:
        """
        Load validation frames from frame name list with their configs.

        Args:
            frame_names: List of frame names (e.g., ['security', 'chaos', 'orphan'])
            frame_config: Frame-specific configurations from config.yaml

        Returns:
            List of initialized ValidationFrame instances
        """
        from warden.validation.frames import (
            SecurityFrame,
            ChaosFrame,
            ArchitecturalConsistencyFrame,
            ProjectArchitectureFrame,
            GitChangesFrame,
            OrphanFrame,
            FuzzFrame,
            PropertyFrame,
            StressFrame,
        )

        if frame_config is None:
            frame_config = {}

        # Map frame names to frame classes
        # NOTE: Config uses underscore names, but frame IDs don't have underscores
        frame_map = {
            'security': SecurityFrame,
            'chaos': ChaosFrame,
            'architectural': ArchitecturalConsistencyFrame,
            'architecturalconsistency': ArchitecturalConsistencyFrame,  # Alternative ID
            'project_architecture': ProjectArchitectureFrame,
            'projectarchitecture': ProjectArchitectureFrame,  # Alternative ID
            'gitchanges': GitChangesFrame,
            'orphan': OrphanFrame,
            'fuzz': FuzzFrame,
            'property': PropertyFrame,
            'stress': StressFrame,
        }

        frames = []

        # Load each frame by name with its config
        for frame_name in frame_names:
            if frame_name in frame_map:
                # Get frame-specific config (e.g., orphan -> orphan config)
                config = frame_config.get(frame_name, {})
                frames.append(frame_map[frame_name](config=config))
            else:
                import sys
                print(f"⚠️  Unknown frame: {frame_name}", file=sys.stderr)

        return frames

    def _get_session_info(self) -> str:
        """Get session info bar text."""
        pipeline_status = "⚙️ Full Pipeline" if self.orchestrator else "⚙️ No Pipeline"

        # ✅ NEW: Show custom rules count if available
        rules_count = 0
        if self.orchestrator and self.orchestrator.config and hasattr(self.orchestrator.config, 'global_rules'):
            rules_count = len(self.orchestrator.config.global_rules)

        info_parts = [
            f"📁 {self.project_root.name}",
            pipeline_status,
            f"📋 {self.active_config_name}",
        ]

        # ✅ NEW: Add rules count if present
        if rules_count > 0:
            info_parts.append(f"📜 {rules_count} rules")

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
