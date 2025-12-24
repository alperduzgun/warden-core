"""Init Command - Initialize Warden configuration for a project."""

import asyncio
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich import box

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from warden.config.project_manager import ProjectConfigManager
from warden.config.project_config import ProjectConfig

app = typer.Typer()
console = Console()


@app.command()
def run(
    directory: str = typer.Argument(
        ".", help="Project directory (default: current directory)"
    ),
    auto: bool = typer.Option(
        False,
        "--auto",
        "-a",
        help="Auto-detect all settings without prompting",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Overwrite existing .warden/project.toml",
    ),
):
    """
    Initialize Warden configuration for a project.

    Creates .warden/project.toml with auto-detected or manually configured settings.

    Examples:
        warden init                    # Interactive setup for current directory
        warden init ./my-project       # Interactive setup for specific directory
        warden init --auto             # Auto-detect all settings
        warden init --force            # Overwrite existing configuration
    """
    asyncio.run(init_project(directory, auto, force))


async def init_project(directory: str, auto: bool, force: bool):
    """Async init logic."""
    dir_path = Path(directory).resolve()

    # Check if directory exists
    if not dir_path.exists():
        console.print(f"[red]Error:[/red] Directory not found: {directory}")
        raise typer.Exit(code=1)

    console.print(
        Panel.fit(
            f"[bold cyan]Warden Project Initialization[/bold cyan]\n"
            f"[dim]Directory:[/dim] {dir_path}",
            title="Init Session",
            border_style="cyan",
        )
    )

    config_manager = ProjectConfigManager(dir_path)

    # Check if config already exists
    if config_manager.config_exists() and not force:
        console.print(
            "\n[yellow]Warning:[/yellow] .warden/project.toml already exists!"
        )
        console.print(f"[dim]Location:[/dim] {config_manager.config_path}")

        # Show existing config
        existing_config = await config_manager.load()
        display_config_table(existing_config)

        overwrite = Confirm.ask(
            "\n[yellow]Do you want to overwrite it?[/yellow]", default=False
        )
        if not overwrite:
            console.print("\n[cyan]Initialization cancelled.[/cyan]")
            raise typer.Exit(code=0)

    # Auto mode: just detect everything
    if auto:
        console.print("\n[cyan]Auto-detecting project settings...[/cyan]")
        config = await config_manager.create_and_save()
        console.print("\n[green]✓[/green] Project configuration created!")
        display_config_table(config)
        console.print(f"\n[dim]Saved to:[/dim] {config_manager.config_path}")
        return

    # Interactive mode
    console.print("\n[cyan]Detecting project settings...[/cyan]\n")

    # Auto-detect first
    from warden.config.project_detector import ProjectDetector

    detector = ProjectDetector(dir_path)
    detected_name = detector.get_project_name()
    detected_language = await detector.detect_language()
    detected_sdk = await detector.detect_sdk_version(detected_language)
    detected_framework = await detector.detect_framework()
    detected_type = await detector.detect_project_type()

    # Show detected values
    console.print("[dim]Auto-detected values:[/dim]")
    console.print(f"  Project Name: [cyan]{detected_name}[/cyan]")
    console.print(f"  Language: [cyan]{detected_language}[/cyan]")
    console.print(
        f"  SDK Version: [cyan]{detected_sdk or 'not detected'}[/cyan]"
    )
    console.print(
        f"  Framework: [cyan]{detected_framework or 'not detected'}[/cyan]"
    )
    console.print(f"  Project Type: [cyan]{detected_type}[/cyan]")

    console.print(
        "\n[yellow]Press Enter to accept detected values or type new ones:[/yellow]\n"
    )

    # Interactive prompts with defaults
    name = Prompt.ask("Project Name", default=detected_name)

    language_choices = [
        "python",
        "java",
        "javascript",
        "typescript",
        "csharp",
        "go",
        "rust",
        "cpp",
        "c",
        "ruby",
        "php",
        "swift",
        "kotlin",
    ]
    if detected_language in language_choices:
        language = Prompt.ask(
            "Language",
            choices=language_choices,
            default=detected_language,
        )
    else:
        console.print(
            f"[yellow]Detected language '{detected_language}' not in standard list[/yellow]"
        )
        language = Prompt.ask(
            "Language",
            choices=language_choices,
            default=language_choices[0],
        )

    sdk_version = Prompt.ask(
        "SDK Version (optional)",
        default=detected_sdk or "",
    )
    if not sdk_version.strip():
        sdk_version = None

    framework = Prompt.ask(
        "Framework (optional)",
        default=detected_framework or "",
    )
    if not framework.strip():
        framework = None

    project_type_choices = ["application", "library", "microservice", "monorepo"]
    project_type = Prompt.ask(
        "Project Type",
        choices=project_type_choices,
        default=detected_type,
    )

    # Create config
    config = ProjectConfig(
        name=name,
        language=language,
        sdk_version=sdk_version,
        framework=framework,
        project_type=project_type,
    )

    # Validate
    issues = config.validate()
    if issues:
        console.print("\n[red]Validation issues:[/red]")
        for issue in issues:
            console.print(f"  - {issue}")
        console.print()
        proceed = Confirm.ask("[yellow]Save anyway?[/yellow]", default=False)
        if not proceed:
            console.print("\n[cyan]Initialization cancelled.[/cyan]")
            raise typer.Exit(code=0)

    # Save config
    await config_manager.save(config)

    console.print("\n[green]✓[/green] Project configuration created!")
    display_config_table(config)
    console.print(f"\n[dim]Saved to:[/dim] {config_manager.config_path}")

    # Show next steps
    console.print("\n[cyan bold]Next Steps:[/cyan bold]")
    console.print("  1. Run [yellow]warden scan[/yellow] to analyze your project")
    console.print(
        "  2. Run [yellow]warden validate <file>[/yellow] to validate a single file"
    )
    console.print(
        "  3. Edit [yellow].warden/project.toml[/yellow] to customize settings"
    )


def display_config_table(config: ProjectConfig):
    """Display project configuration in a table."""
    table = Table(
        title="Project Configuration",
        box=box.ROUNDED,
        show_header=False,
    )
    table.add_column("Setting", style="cyan bold", width=20)
    table.add_column("Value", style="white")

    table.add_row("Name", config.name)
    table.add_row("Language", config.language)
    table.add_row("SDK Version", config.sdk_version or "[dim]not set[/dim]")
    table.add_row("Framework", config.framework or "[dim]not set[/dim]")
    table.add_row("Project Type", config.project_type)
    table.add_row(
        "Detected At", config.detected_at.strftime("%Y-%m-%d %H:%M:%S")
    )

    console.print(table)


if __name__ == "__main__":
    app()
