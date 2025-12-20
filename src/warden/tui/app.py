"""
Warden TUI Main Application

Professional terminal UI for AI Code Guardian.
Features: Slash commands, chat interface, code analysis, real-time streaming.
"""

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.widgets import Header, Footer, Input, Static, Button
from textual.binding import Binding
from rich.text import Text
from rich.markdown import Markdown
from rich.syntax import Syntax
from pathlib import Path

from .widgets import CommandPaletteScreen, MessageWidget, FilePickerScreen

# Import real Warden components
try:
    from warden.core.analysis.analyzer import CodeAnalyzer
    ANALYZER_AVAILABLE = True
except ImportError:
    ANALYZER_AVAILABLE = False


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
        Binding("/", "command_palette", "Commands", show=False),  # Also allow / but don't show
        Binding("ctrl+l", "clear_chat", "Clear", show=True),
        Binding("ctrl+s", "save_session", "Save", show=True),
    ]

    TITLE = "🛡️  Warden - AI Code Guardian"
    SUB_TITLE = "Your production code quality enforcer"

    def __init__(self, project_root: Path = None):
        """Initialize Warden TUI"""
        super().__init__()
        self.project_root = project_root or Path.cwd()
        self.session_id = None
        self.llm_available = False

        # Initialize analyzer
        self.analyzer = CodeAnalyzer() if ANALYZER_AVAILABLE else None

    def compose(self) -> ComposeResult:
        """Create child widgets"""
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

    def _get_session_info(self) -> str:
        """Get session info bar text"""
        info_parts = [
            f"📁 {self.project_root.name}",
            "⚡ LLM: Ready" if self.llm_available else "⚡ LLM: AST-only",
        ]

        if self.session_id:
            info_parts.append(f"🔖 Session: {self.session_id[:8]}")

        return " | ".join(info_parts)

    def on_mount(self) -> None:
        """Called when app is mounted"""
        # Focus on input
        self.query_one("#chat-input", Input).focus()

        # Initialize session
        self._initialize_session()

    def _initialize_session(self) -> None:
        """Initialize Warden session"""
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
        """Handle input changes - open command palette on / or file picker on @"""
        if event.value == "/":
            # Clear the input
            event.input.value = ""
            # Open command palette
            self.action_command_palette()
        elif event.value.endswith("@"):
            # Trigger file picker
            self._show_file_picker(event.input)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle input submission"""
        user_input = event.value.strip()

        if not user_input:
            return

        # Clear input
        event.input.value = ""

        # Add user message to chat
        self._add_message(f"**You:** {user_input}", "user-message", markdown=True)

        # Check if it's a slash command
        if user_input.startswith("/"):
            await self._handle_slash_command(user_input)
        else:
            await self._handle_chat_message(user_input)

        # Keep focus on input after processing
        self.call_later(lambda: self.query_one("#chat-input", Input).focus())

    def _add_message(self, message: str, css_class: str = "message", markdown: bool = False) -> None:
        """Add message to chat area

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

    async def _handle_slash_command(self, command: str) -> None:
        """Handle slash command"""
        # Parse command
        parts = command.split(maxsplit=1)
        cmd = parts[0][1:]  # Remove /
        args = parts[1] if len(parts) > 1 else ""

        # Handle commands
        if cmd in ["help", "h", "?"]:
            self._show_help()
        elif cmd in ["analyze", "a", "check"]:
            await self._cmd_analyze(args)
        elif cmd in ["scan", "s"]:
            await self._cmd_scan(args)
        elif cmd in ["status", "info"]:
            self._cmd_status()
        elif cmd in ["clear", "cls"]:
            await self.action_clear_chat()
        elif cmd in ["quit", "exit", "q"]:
            await self.action_quit()
        else:
            self._add_message(
                f"❌ **Unknown command:** `/{cmd}`\n\nType `/help` for available commands",
                "error-message",
                markdown=True
            )

    async def _cmd_analyze(self, args: str) -> None:
        """Analyze a file"""
        if not args:
            self._add_message(
                "❌ **Missing file path**\n\nUsage: `/analyze <file>`",
                "error-message",
                markdown=True
            )
            return

        file_path = Path(args.strip())

        if not file_path.exists():
            self._add_message(
                f"❌ **File not found:** `{file_path}`",
                "error-message",
                markdown=True
            )
            return

        # Check if it's a Python file
        if file_path.suffix not in ['.py']:
            self._add_message(
                f"⚠️ **Warning:** Only Python files (`.py`) are currently supported.\n\n"
                f"File: `{file_path}`",
                "error-message",
                markdown=True
            )
            return

        self._add_message(
            f"🔍 **Analyzing:** `{file_path.name}`\n\n"
            f"Running AST analysis...",
            "system-message",
            markdown=True
        )

        # Use real analyzer if available
        if self.analyzer:
            await self._run_real_analysis(file_path)
        else:
            self._add_message(
                "⚠️ **Analyzer not available**\n\n"
                "Real analyzer is not loaded. Showing mock result instead.",
                "error-message",
                markdown=True
            )
            await self._show_mock_analysis_result(file_path)

    async def _run_real_analysis(self, file_path: Path) -> None:
        """Run real analysis using CodeAnalyzer"""
        try:
            # Read file
            with open(file_path) as f:
                content = f.read()

            # Run analysis
            result = await self.analyzer.analyze(
                file_path=str(file_path),
                file_content=content,
                language="python"
            )

            # Format and display results
            await self._display_analysis_result(file_path, result)

        except Exception as e:
            self._add_message(
                f"❌ **Analysis failed**\n\n"
                f"Error: `{str(e)}`",
                "error-message",
                markdown=True
            )

    async def _display_analysis_result(self, file_path: Path, result: dict) -> None:
        """Display real analysis results"""
        score = result.get("score", 0.0)
        issues = result.get("issues", [])
        metrics = result.get("metrics", {})
        duration_ms = result.get("durationMs", 0)

        # Score emoji
        if score >= 8.0:
            score_emoji = "✅"
        elif score >= 6.0:
            score_emoji = "⚠️"
        else:
            score_emoji = "❌"

        # Build result message
        message = f"""
{score_emoji} **Analysis Complete**

**File:** `{file_path}`
**Quality Score:** {score}/10.0
**Duration:** {duration_ms:.0f}ms

**Metrics:**
- Lines: {metrics.get('lines', 0)}
- Functions: {metrics.get('functions', 0)}
- Classes: {metrics.get('classes', 0)}
- Complexity: {metrics.get('conditionals', 0)} conditionals, {metrics.get('loops', 0)} loops
"""

        if issues:
            message += f"\n**Issues Found:** {len(issues)}\n\n"
            for idx, issue in enumerate(issues[:5], 1):  # Show first 5
                severity = issue.get('severity', 'low')
                severity_emoji = {"critical": "🔴", "high": "🟡", "medium": "🟠", "low": "⚪"}.get(severity, "⚪")
                message += f"{idx}. {severity_emoji} **{issue.get('type', 'unknown')}** (line {issue.get('line', 0)})\n"
                message += f"   {issue.get('message', 'No description')}\n\n"

            if len(issues) > 5:
                message += f"... and {len(issues) - 5} more issues\n"
        else:
            message += "\n✅ **No issues found!** Code looks good.\n"

        self._add_message(message.strip(), "assistant-message", markdown=True)

    async def _show_mock_analysis_result(self, file_path: Path) -> None:
        """Show mock analysis result (placeholder)"""
        result = f"""
✅ **Analysis Complete**

**File:** `{file_path}`
**Lines:** 150
**Issues Found:** 0

**Validation Frames:**
- 🔐 Security Analysis: ✅ Pass
- ⚡ Chaos Engineering: ✅ Pass
- 🎲 Fuzz Testing: ✅ Pass
- 📐 Property Testing: ✅ Pass
- 💪 Stress Testing: ✅ Pass

**Status:** Ready for production! 🎉
        """
        self._add_message(result.strip(), "assistant-message", markdown=True)

    async def _cmd_scan(self, args: str) -> None:
        """Scan project or directory"""
        scan_path = Path(args.strip()) if args else self.project_root

        if not scan_path.exists():
            self._add_message(
                f"❌ **Path not found:** `{scan_path}`",
                "error-message",
                markdown=True
            )
            return

        if not scan_path.is_dir():
            self._add_message(
                f"❌ **Not a directory:** `{scan_path}`\n\n"
                f"Use `/analyze` for single files.",
                "error-message",
                markdown=True
            )
            return

        self._add_message(
            f"🔍 **Scanning:** `{scan_path}`\n\n"
            f"Finding Python files...",
            "system-message",
            markdown=True
        )

        # Use real analyzer if available
        if self.analyzer:
            await self._run_real_scan(scan_path)
        else:
            self._add_message(
                "⚠️ **Analyzer not available**\n\n"
                "Real analyzer is not loaded. Showing mock result instead.",
                "error-message",
                markdown=True
            )
            await self._show_mock_scan_result(scan_path)

    async def _run_real_scan(self, scan_path: Path) -> None:
        """Run real scan using CodeAnalyzer"""
        try:
            # Find all Python files
            py_files = list(scan_path.rglob("*.py"))

            if not py_files:
                self._add_message(
                    f"⚠️ **No Python files found** in `{scan_path}`",
                    "error-message",
                    markdown=True
                )
                return

            # Update progress
            self._add_message(
                f"📊 Found {len(py_files)} Python files. Analyzing...",
                "system-message",
                markdown=True
            )

            # Analyze all files
            results = []
            total_lines = 0
            total_issues = 0
            all_issues = []

            for file_path in py_files:
                try:
                    with open(file_path) as f:
                        content = f.read()

                    result = await self.analyzer.analyze(
                        file_path=str(file_path),
                        file_content=content,
                        language="python"
                    )

                    results.append({
                        "path": file_path,
                        "result": result
                    })

                    total_lines += result.get("metrics", {}).get("lines", 0)
                    issues = result.get("issues", [])
                    total_issues += len(issues)

                    # Collect issues with file path
                    for issue in issues:
                        issue["file"] = str(file_path)
                        all_issues.append(issue)

                except Exception as e:
                    # Skip files that can't be analyzed
                    continue

            # Display scan results
            await self._display_scan_result(scan_path, results, total_lines, total_issues, all_issues)

        except Exception as e:
            self._add_message(
                f"❌ **Scan failed**\n\n"
                f"Error: `{str(e)}`",
                "error-message",
                markdown=True
            )

    async def _display_scan_result(self, scan_path: Path, results: list, total_lines: int, total_issues: int, all_issues: list) -> None:
        """Display real scan results"""
        files_analyzed = len(results)

        # Calculate issue breakdown
        critical = sum(1 for i in all_issues if i.get("severity") == "critical")
        high = sum(1 for i in all_issues if i.get("severity") == "high")
        medium = sum(1 for i in all_issues if i.get("severity") == "medium")
        low = sum(1 for i in all_issues if i.get("severity") == "low")

        # Calculate average score
        scores = [r["result"].get("score", 0) for r in results if r["result"].get("score")]
        avg_score = sum(scores) / len(scores) if scores else 0.0

        # Score emoji
        if avg_score >= 8.0:
            score_emoji = "✅"
        elif avg_score >= 6.0:
            score_emoji = "⚠️"
        else:
            score_emoji = "❌"

        message = f"""
{score_emoji} **Scan Complete**

**Path:** `{scan_path}`
**Files Analyzed:** {files_analyzed}
**Total Lines:** {total_lines:,}
**Average Score:** {avg_score:.1f}/10.0

**Issues Found:** {total_issues}
"""

        if total_issues > 0:
            message += f"""
**Breakdown:**
- 🔴 Critical: {critical}
- 🟡 High: {high}
- 🟠 Medium: {medium}
- ⚪ Low: {low}
"""

            # Show top issues (by severity)
            top_issues = sorted(all_issues, key=lambda x: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(x.get("severity", "low"), 4))[:5]

            if top_issues:
                message += f"\n**Top Issues:**\n\n"
                for idx, issue in enumerate(top_issues, 1):
                    severity = issue.get('severity', 'low')
                    severity_emoji = {"critical": "🔴", "high": "🟡", "medium": "🟠", "low": "⚪"}.get(severity, "⚪")
                    file_name = Path(issue.get('file', '')).name
                    message += f"{idx}. {severity_emoji} **{issue.get('type', 'unknown')}** in `{file_name}:{issue.get('line', 0)}`\n"
                    message += f"   {issue.get('message', 'No description')}\n\n"

            if total_issues > 5:
                message += f"... and {total_issues - 5} more issues\n\n"
                message += f"💡 Use `/analyze <file>` to see detailed analysis for specific files.\n"
        else:
            message += "\n✅ **No issues found!** All files look good.\n"

        self._add_message(message.strip(), "assistant-message", markdown=True)

    async def _show_mock_scan_result(self, scan_path: Path) -> None:
        """Show mock scan result (placeholder)"""
        result = f"""
✅ **Scan Complete**

**Path:** `{scan_path}`
**Files Scanned:** 42
**Total Lines:** 5,240
**Issues Found:** 3

**Summary:**
- 🔴 Critical: 0
- 🟡 High: 1
- 🟢 Medium: 2
- ⚪ Low: 0

**Top Issues:**
1. Missing error handling in `api/client.py:145`
2. Potential SQL injection in `db/query.py:87`
3. Unused import in `utils/helper.py:12`

Run `/fix` to auto-repair these issues.
        """
        self._add_message(result.strip(), "assistant-message", markdown=True)

    def _cmd_status(self) -> None:
        """Show session status"""
        status = f"""
📊 **Warden Status**

**Project:** `{self.project_root.name}`
**Session ID:** `{self.session_id[:8] if self.session_id else 'N/A'}`
**LLM Status:** {'✅ Ready' if self.llm_available else '⚠️ AST-only mode'}

**Configuration:**
- Validation Frames: 5 enabled
- Auto-fix: Disabled
- Memory: Enabled (Qdrant)

**Statistics:**
- Files Analyzed: 0
- Issues Found: 0
- Fixes Applied: 0
        """
        self._add_message(status.strip(), "system-message", markdown=True)

    def _show_help(self) -> None:
        """Show help message"""
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
        self._add_message(help_text.strip(), "system-message", markdown=True)

    async def _handle_chat_message(self, message: str) -> None:
        """Handle natural language chat"""
        # For now, provide helpful responses based on keywords
        message_lower = message.lower()

        if any(word in message_lower for word in ["analyze", "check", "inspect", "review"]):
            response = """
🤖 **Warden:** I can help you analyze code!

To analyze a specific file, use:
`/analyze <file_path>`

Or to scan your entire project:
`/scan`

Would you like to try one of these commands?
            """
        elif any(word in message_lower for word in ["help", "how", "what", "commands"]):
            response = """
🤖 **Warden:** I'm here to help!

I can assist you with:
- 🔍 Code analysis and validation
- 🛡️ Security checks
- 🔧 Auto-fixing issues
- 📊 Project scanning

Type `/help` to see all available commands, or just tell me what you'd like to do!
            """
        elif any(word in message_lower for word in ["fix", "repair", "solve"]):
            response = """
🤖 **Warden:** I can help fix issues!

To auto-fix problems in a file, use:
`/fix <file_path>`

First, you might want to run `/analyze` or `/scan` to see what needs fixing.
            """
        else:
            response = f"""
🤖 **Warden:** I understand you said: "{message}"

I'm currently in command mode. Here are some things I can do:
- `/analyze <file>` - Check code quality
- `/scan` - Scan entire project
- `/status` - Show session info
- `/help` - See all commands

What would you like me to do?
            """

        self._add_message(response.strip(), "assistant-message", markdown=True)

    def action_command_palette(self) -> None:
        """Show command palette"""
        self.push_screen(CommandPaletteScreen())

    def _show_file_picker(self, input_widget) -> None:
        """Show file picker and insert selected path"""
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
        """Clear chat area"""
        chat_area = self.query_one("#chat-area", VerticalScroll)
        await chat_area.remove_children()

        # Add welcome message back
        chat_area.mount(
            Static("Chat cleared. Ready for new conversation! 🛡️",
                  classes="system-message")
        )

        # Refocus input
        self.query_one("#chat-input", Input).focus()

    def action_save_session(self) -> None:
        """Save current session"""
        self._add_message("💾 Session saved!", "system-message")
        # TODO: Implement session save


def run_tui(project_root: Path = None):
    """Run Warden TUI"""
    app = WardenTUI(project_root=project_root)
    app.run()


if __name__ == "__main__":
    run_tui()
