"""
Warden Interactive Mode - QwenCode/Claude Code-like experience

Interactive conversational CLI for code analysis and fixing
"""

import asyncio
import sys
from pathlib import Path
from typing import Optional, List
from datetime import datetime

from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.table import Table
from rich.live import Live
from rich.spinner import Spinner
from rich.progress import Progress, SpinnerColumn, TextColumn

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import WordCompleter
    from prompt_toolkit.history import InMemoryHistory
    PROMPT_TOOLKIT_AVAILABLE = True
except ImportError:
    PROMPT_TOOLKIT_AVAILABLE = False


class WardenInteractive:
    """
    Interactive Warden CLI session

    Provides conversational interface for code analysis, fixing, and validation
    Similar to Claude Code and QwenCode
    """

    def __init__(self, project_root: Optional[Path] = None):
        """Initialize interactive session"""
        self.console = Console()
        self.project_root = project_root or Path.cwd()
        self.current_file: Optional[Path] = None
        self.context: List[str] = []  # Conversation history
        self.llm_factory = None

        # Command completions
        self.commands = [
            'analyze', 'scan', 'fix', 'explain', 'help',
            'exit', 'quit', 'status', 'config', 'report',
            'validate', 'test', 'commit', 'diff', 'watch'
        ]

    def display_banner(self):
        """Display welcome banner"""
        banner = """
[bold cyan]🛡️  Warden - AI Code Guardian[/bold cyan]
[dim]Version 1.0.0 | Interactive Mode[/dim]

Type [bold green]'help'[/bold green] for commands or just chat naturally
Type [bold red]'exit'[/bold red] to quit
        """

        self.console.print(Panel(
            banner.strip(),
            border_style="cyan",
            padding=(1, 2)
        ))

        # Show project info
        self.console.print(f"📁 Project: [cyan]{self.project_root}[/cyan]")

        # Check for config
        config_file = self.project_root / ".warden.yaml"
        if config_file.exists():
            self.console.print(f"🔧 Config: [green].warden.yaml found[/green]")
        else:
            self.console.print(f"🔧 Config: [yellow]No .warden.yaml (using defaults)[/yellow]")

        # Check LLM availability
        try:
            from warden.llm import LlmConfiguration, LlmClientFactory, create_default_config
            import os

            if os.getenv("AZURE_OPENAI_API_KEY"):
                self.console.print("⚡ LLM: [green]Azure GPT-4o (ready)[/green]")

                # Initialize LLM factory
                config = create_default_config()
                from warden.llm.config import ProviderConfig, LlmProvider
                config.default_provider = LlmProvider.AZURE_OPENAI
                config.azure_openai = ProviderConfig(
                    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
                    endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
                    default_model="gpt-4o",
                    api_version="2024-02-01",
                    enabled=True
                )
                self.llm_factory = LlmClientFactory(config)
            else:
                self.console.print("⚡ LLM: [yellow]No API key (AST-only mode)[/yellow]")
        except Exception as e:
            self.console.print(f"⚡ LLM: [red]Error: {e}[/red]")

        self.console.print()

    def display_help(self):
        """Display help information"""
        help_table = Table(title="Warden Commands", show_header=True)
        help_table.add_column("Command", style="cyan", width=20)
        help_table.add_column("Description", style="white")

        help_table.add_row("analyze <file>", "Analyze a specific file")
        help_table.add_row("scan", "Scan entire project")
        help_table.add_row("fix", "Auto-fix issues in current file")
        help_table.add_row("explain <line>", "Explain code at specific line")
        help_table.add_row("validate", "Run validation frames")
        help_table.add_row("diff", "Analyze git changes")
        help_table.add_row("commit", "Commit with AI message")
        help_table.add_row("status", "Show current status")
        help_table.add_row("help", "Show this help")
        help_table.add_row("exit/quit", "Exit interactive mode")

        self.console.print(help_table)
        self.console.print()
        self.console.print("[dim]💡 Tip: You can also use natural language![/dim]")
        self.console.print("[dim]   Example: 'analyze this file and fix security issues'[/dim]")

    async def parse_natural_language(self, user_input: str) -> dict:
        """Parse natural language using LLM"""
        if not self.llm_factory:
            # Fallback to keyword matching
            return self.parse_keywords(user_input)

        try:
            from warden.llm import LlmRequest

            client = await self.llm_factory.create_client_with_fallback()

            system_prompt = """You are a command parser for Warden CLI.
Parse user input into structured commands.

Available commands:
- analyze <file>: Analyze a file
- scan: Scan project
- fix: Fix issues
- explain <line>: Explain code
- help: Show help
- exit: Exit

Return JSON:
{
  "command": "analyze|scan|fix|explain|help|exit",
  "args": {"file": "path", "line": 45},
  "intent": "brief description"
}"""

            request = LlmRequest(
                system_prompt=system_prompt,
                user_message=f"Parse this command: {user_input}",
                max_tokens=200,
                timeout_seconds=10
            )

            response = await client.send_async(request)

            if response.success:
                import json
                content = response.content.strip()
                if content.startswith("```json"):
                    content = content[7:-3].strip()
                return json.loads(content)
            else:
                return self.parse_keywords(user_input)

        except Exception as e:
            self.console.print(f"[dim]⚠️  NL parse failed: {e}[/dim]")
            return self.parse_keywords(user_input)

    def parse_keywords(self, user_input: str) -> dict:
        """Fallback keyword-based parsing"""
        lower = user_input.lower().strip()

        if any(word in lower for word in ['help', '?']):
            return {"command": "help"}
        elif any(word in lower for word in ['exit', 'quit', 'bye']):
            return {"command": "exit"}
        elif 'analyze' in lower or 'check' in lower:
            # Extract file path
            words = user_input.split()
            file_path = next((w for w in words if '.' in w or '/' in w), None)
            return {"command": "analyze", "args": {"file": file_path}}
        elif 'scan' in lower:
            return {"command": "scan"}
        elif 'fix' in lower:
            return {"command": "fix"}
        elif 'status' in lower:
            return {"command": "status"}
        else:
            return {"command": "unknown", "input": user_input}

    async def execute_command(self, parsed: dict):
        """Execute parsed command"""
        command = parsed.get("command")
        args = parsed.get("args", {})

        if command == "help":
            self.display_help()

        elif command == "exit":
            self.console.print("\n[cyan]👋 Goodbye! Your code is safer now.[/cyan]")
            return False

        elif command == "analyze":
            await self.cmd_analyze(args.get("file"))

        elif command == "scan":
            await self.cmd_scan()

        elif command == "fix":
            await self.cmd_fix()

        elif command == "status":
            self.cmd_status()

        elif command == "unknown":
            self.console.print(f"[yellow]❓ I didn't understand that. Type 'help' for commands.[/yellow]")
            self.console.print(f"[dim]You said: {parsed.get('input')}[/dim]")

        return True

    async def cmd_analyze(self, file_path: Optional[str]):
        """Analyze a file"""
        if not file_path:
            file_path = self.current_file

        if not file_path:
            self.console.print("[yellow]❓ Which file should I analyze?[/yellow]")
            return

        file_path = Path(file_path)
        if not file_path.exists():
            self.console.print(f"[red]❌ File not found: {file_path}[/red]")
            return

        self.current_file = file_path

        # Show progress
        with self.console.status(f"[cyan]🔍 Analyzing {file_path.name}...[/cyan]"):
            try:
                from warden.core.analysis.analyzer import CodeAnalyzer

                code = file_path.read_text()
                analyzer = CodeAnalyzer(llm_factory=self.llm_factory)

                if self.llm_factory:
                    result = await analyzer.analyze_with_llm(str(file_path), code, "python")
                    provider = result.get("provider", "LLM")
                else:
                    result = await analyzer.analyze(str(file_path), code, "python")
                    provider = "AST"

                # Display results
                score = result.get("score", 0)
                issues = result.get("issues", [])

                # Score panel
                score_color = "green" if score >= 8 else "yellow" if score >= 6 else "red"
                self.console.print(Panel(
                    f"[bold {score_color}]Score: {score}/10[/bold {score_color}]\n"
                    f"[dim]Provider: {provider}[/dim]\n"
                    f"[dim]Issues: {len(issues)} found[/dim]",
                    title=f"✅ Analysis Complete",
                    border_style="green"
                ))

                # Show issues
                if issues:
                    self.console.print("\n[bold red]❌ Issues Found:[/bold red]")
                    for issue in issues[:5]:  # Show first 5
                        severity = issue.get("severity", "unknown")
                        title = issue.get("title", issue.get("type", "Issue"))
                        line = issue.get("line", "?")

                        severity_icon = "🔴" if severity == "critical" else "🟡" if severity == "high" else "🟢"
                        self.console.print(f"  {severity_icon} [bold]{title}[/bold] (line {line})")

                    if len(issues) > 5:
                        self.console.print(f"  [dim]... and {len(issues) - 5} more[/dim]")
                else:
                    self.console.print("\n[green]✅ No issues found! Code looks good.[/green]")

            except Exception as e:
                self.console.print(f"[red]❌ Analysis failed: {e}[/red]")

    async def cmd_scan(self):
        """Scan entire project"""
        self.console.print("[cyan]🔍 Scanning project...[/cyan]")
        self.console.print("[dim]This feature is coming soon![/dim]")

    async def cmd_fix(self):
        """Auto-fix issues"""
        if not self.current_file:
            self.console.print("[yellow]❓ No file selected. Use 'analyze <file>' first.[/yellow]")
            return

        self.console.print("[cyan]🔧 Auto-fix feature coming soon![/cyan]")

    def cmd_status(self):
        """Show current status"""
        table = Table(title="Current Status")
        table.add_column("Property", style="cyan")
        table.add_column("Value", style="white")

        table.add_row("Project", str(self.project_root))
        table.add_row("Current File", str(self.current_file) if self.current_file else "[dim]None[/dim]")
        table.add_row("LLM Available", "Yes" if self.llm_factory else "No")
        table.add_row("Commands Run", str(len(self.context)))

        self.console.print(table)

    async def run(self):
        """Run interactive session"""
        self.display_banner()

        # Setup prompt
        if PROMPT_TOOLKIT_AVAILABLE:
            completer = WordCompleter(self.commands, ignore_case=True)
            history = InMemoryHistory()
            session = PromptSession(
                completer=completer,
                history=history
            )
        else:
            session = None
            self.console.print("[yellow]⚠️  Install prompt_toolkit for better experience[/yellow]")
            self.console.print("[dim]pip install prompt_toolkit[/dim]\n")

        # Main loop
        while True:
            try:
                # Get input
                if session:
                    user_input = await asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda: session.prompt("warden> ")
                    )
                else:
                    user_input = input("warden> ")

                if not user_input.strip():
                    continue

                # Add to context
                self.context.append(user_input)

                # Parse command
                parsed = await self.parse_natural_language(user_input)

                # Execute
                should_continue = await self.execute_command(parsed)

                if not should_continue:
                    break

                self.console.print()  # Blank line

            except KeyboardInterrupt:
                self.console.print("\n[yellow]Use 'exit' to quit[/yellow]")
                continue
            except EOFError:
                break
            except Exception as e:
                self.console.print(f"[red]❌ Error: {e}[/red]")


async def main():
    """Entry point for interactive mode"""
    session = WardenInteractive()
    await session.run()


if __name__ == "__main__":
    asyncio.run(main())
