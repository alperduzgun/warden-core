"""
CLI command for initializing Warden in a project.

Automatically detects project language, framework, and generates
appropriate configuration files.
"""

import sys
import subprocess
from pathlib import Path
from typing import Optional

import typer
import structlog
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table

from warden.config.project_detector import ProjectDetector
from warden.config.project_manager import ProjectConfigManager
from warden.config.config_generator import ConfigGenerator
from warden.config.language_templates import (
    get_language_template,
    get_supported_languages,
    GENERIC_TEMPLATE,
)

# Initialize Typer app and console
app = typer.Typer(
    name="init",
    help="Initialize Warden configuration for your project"
)
console = Console()
logger = structlog.get_logger(__name__)


@app.callback(invoke_without_command=True)
def init_project(
    ctx: typer.Context,
    interactive: bool = typer.Option(
        True,
        "--interactive/--no-interactive",
        "-i/-n",
        help="Interactive mode (prompts for confirmation)"
    ),
    language: Optional[str] = typer.Option(
        None,
        "--language",
        "-l",
        help="Force specific language (auto-detect if not specified)"
    ),
    install_providers: bool = typer.Option(
        True,
        "--install-providers/--no-install-providers",
        help="Automatically install required AST providers"
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Overwrite existing configuration"
    ),
) -> None:
    """
    Initialize Warden configuration for this project.

    Automatically detects:
    - Programming language
    - Framework
    - Project type
    - SDK version

    Generates:
    - .warden/project.toml (project metadata)
    - .warden/config.yaml (pipeline configuration)

    Installs:
    - Required AST providers for detected language

    Examples:
        # Auto-detect everything
        warden init

        # Force Python configuration
        warden init --language python

        # Non-interactive mode (for CI/CD)
        warden init --no-interactive

        # Skip provider installation
        warden init --no-install-providers
    """
    # Use asyncio to run async function
    import asyncio
    asyncio.run(_init_project_async(
        interactive=interactive,
        language=language,
        install_providers=install_providers,
        force=force
    ))


async def _init_project_async(
    interactive: bool,
    language: Optional[str],
    install_providers: bool,
    force: bool
) -> None:
    """Async implementation of init project."""
    console.print("\n[bold cyan]🛡️  Warden Initialization[/bold cyan]\n")

    project_root = Path.cwd()
    warden_dir = project_root / ".warden"

    # Check if already initialized
    if warden_dir.exists() and not force:
        if (warden_dir / "config.yaml").exists():
            console.print(
                "[yellow]⚠️  Warden already initialized in this project[/yellow]\n"
            )
            console.print("Existing files found:")
            if (warden_dir / "project.toml").exists():
                console.print("  • .warden/project.toml")
            if (warden_dir / "config.yaml").exists():
                console.print("  • .warden/config.yaml")
            console.print("\nUse --force to overwrite existing configuration")
            raise typer.Exit(1)

    # STEP 1: Detect or use specified language
    detector = ProjectDetector(project_root)

    if language:
        detected_language = language.lower()
        console.print(f"[dim]Using specified language:[/dim] {detected_language}")
    else:
        console.print("[cyan]Detecting project language...[/cyan]")
        detected_language = await detector.detect_language()

        if detected_language == "unknown":
            console.print(
                "[yellow]⚠️  Could not detect project language[/yellow]\n"
            )
            if interactive:
                # Show supported languages
                console.print("Supported languages:")
                supported = get_supported_languages()
                for lang in sorted(supported):
                    console.print(f"  • {lang}")
                console.print("")

                # Prompt for language
                language_input = typer.prompt(
                    "Please specify the language",
                    default="python"
                )
                detected_language = language_input.lower()
            else:
                console.print(
                    "[red]Cannot proceed without language detection[/red]\n"
                    "Use --language to specify the language manually"
                )
                raise typer.Exit(1)
        else:
            console.print(f"[green]✓ Detected language:[/green] {detected_language}")

    # Get language template
    template = get_language_template(detected_language)
    if template == GENERIC_TEMPLATE:
        console.print(
            f"[yellow]⚠️  No specific template for '{detected_language}'[/yellow]"
        )
        console.print("[dim]Using generic configuration[/dim]\n")

    # STEP 2: Detect framework and SDK version
    console.print("[cyan]Detecting framework and SDK version...[/cyan]")

    framework = await detector.detect_framework()
    sdk_version = await detector.detect_sdk_version(detected_language)
    project_type = await detector.detect_project_type()
    project_name = detector.get_project_name()

    if framework:
        console.print(f"[green]✓ Framework:[/green] {framework}")
    if sdk_version:
        console.print(f"[green]✓ SDK Version:[/green] {sdk_version}")
    if project_type:
        console.print(f"[green]✓ Project Type:[/green] {project_type}")

    console.print(f"[green]✓ Project Name:[/green] {project_name}")

    # STEP 3: Display recommended configuration
    console.print("\n[bold]📋 Recommended Configuration[/bold]\n")

    # Create configuration table
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Language", detected_language)
    table.add_row("Framework", framework or "None")
    table.add_row("SDK Version", sdk_version or "Auto-detect")
    table.add_row("Project Type", project_type)
    table.add_row("Validation Frames", ", ".join(template.recommended_frames))
    table.add_row(
        "AST Providers",
        ", ".join(template.required_ast_providers)
    )
    table.add_row(
        "LLM Analysis",
        "✅ Recommended" if template.llm_recommended else "❌ Not required"
    )

    console.print(table)

    if template.description:
        console.print(f"\n[dim]{template.description}[/dim]")

    # STEP 4: Confirm with user (if interactive)
    if interactive:
        console.print("")
        proceed = Confirm.ask("Proceed with this configuration?", default=True)
        if not proceed:
            console.print("[yellow]Initialization cancelled[/yellow]")
            raise typer.Exit(0)

    # STEP 5: Create project.toml
    console.print("\n[cyan]Creating .warden/project.toml...[/cyan]")

    try:
        config_manager = ProjectConfigManager(project_root)

        # Force create if --force is used
        if force and config_manager.config_exists():
            await config_manager.delete()

        project_config = await config_manager.create_and_save()
        console.print("[green]✓ Project metadata saved[/green]")
    except Exception as e:
        console.print(f"[red]✗ Failed to create project.toml: {e}[/red]")
        raise typer.Exit(1)

    # STEP 6: Generate config.yaml
    console.print("[cyan]Creating .warden/config.yaml...[/cyan]")

    try:
        generator = ConfigGenerator(project_root)
        config_data = await generator.generate_config(
            language=detected_language,
            project_name=project_name,
            framework=framework,
            sdk_version=sdk_version,
            interactive=interactive,
        )

        config_path = await generator.save_config(config_data)
        console.print("[green]✓ Pipeline configuration saved[/green]")
    except Exception as e:
        console.print(f"[red]✗ Failed to create config.yaml: {e}[/red]")
        raise typer.Exit(1)

    # STEP 7: Install required AST providers
    if install_providers and template.required_ast_providers:
        # Filter out built-in providers
        external_providers = [
            p for p in template.required_ast_providers
            if p not in ["python-native", "tree-sitter"]
        ]

        if external_providers:
            console.print(
                f"\n[cyan]Installing AST providers: {', '.join(external_providers)}[/cyan]"
            )

            for provider_package in external_providers:
                try:
                    # Run pip install
                    result = subprocess.run(
                        [sys.executable, "-m", "pip", "install", provider_package],
                        capture_output=True,
                        text=True,
                        timeout=300,  # 5 minutes timeout
                    )

                    if result.returncode == 0:
                        console.print(f"[green]✓ Installed {provider_package}[/green]")
                    else:
                        console.print(
                            f"[yellow]⚠️  Failed to install {provider_package}[/yellow]"
                        )
                        console.print(f"[dim]Error: {result.stderr}[/dim]")
                except subprocess.TimeoutExpired:
                    console.print(
                        f"[yellow]⚠️  Installation timed out for {provider_package}[/yellow]"
                    )
                except Exception as e:
                    console.print(
                        f"[yellow]⚠️  Error installing {provider_package}: {e}[/yellow]"
                    )

    # STEP 8: Display success summary
    console.print(
        Panel.fit(
            f"[bold green]✓ Warden initialized successfully![/bold green]\n\n"
            f"[dim]Configuration:[/dim]\n"
            f"  • Language: {detected_language}\n"
            f"  • Framework: {framework or 'None'}\n"
            f"  • Frames: {len(template.recommended_frames)}\n"
            f"  • Config: .warden/config.yaml\n\n"
            f"[dim]Next steps:[/dim]\n"
            f"  1. Review .warden/config.yaml\n"
            f"  2. Set LLM API key (if using): export ANTHROPIC_API_KEY=...\n"
            f"  3. Run: [cyan]warden scan[/cyan]\n"
            f"  4. Interactive mode: [cyan]warden-chat[/cyan]",
            title="🎉 Initialization Complete",
            border_style="green",
        )
    )

    # Log summary
    logger.info(
        "warden_initialized",
        language=detected_language,
        framework=framework,
        sdk_version=sdk_version,
        project_type=project_type,
        frames=template.recommended_frames,
    )


if __name__ == "__main__":
    app()