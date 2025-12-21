"""
CLI commands for managing AST providers.

This module provides commands to:
- List installed providers
- Install providers from PyPI
- Remove providers
- Test provider availability

Usage:
    warden providers list
    warden providers install java
    warden providers remove java
    warden providers test python
"""

import sys
import subprocess
from typing import Dict

import typer
import structlog
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from warden.ast.domain.enums import CodeLanguage
from warden.ast.application.provider_registry import ASTProviderRegistry

# Initialize Typer app and console
app = typer.Typer(
    name="providers",
    help="Manage AST providers for different programming languages"
)
console = Console()
logger = structlog.get_logger(__name__)

# Provider package mapping: language name -> PyPI package name
PROVIDER_MAP: Dict[str, str] = {
    'java': 'warden-ast-java',
    'csharp': 'warden-ast-csharp',
    'typescript': 'warden-ast-typescript',
    'kotlin': 'warden-ast-kotlin',
    'go': 'warden-ast-go',
    'rust': 'warden-ast-rust',
    'php': 'warden-ast-php',
    'ruby': 'warden-ast-ruby',
    'swift': 'warden-ast-swift',
    'cpp': 'warden-ast-cpp',
    'c': 'warden-ast-c',
    'dart': 'warden-ast-dart',
}


@app.command()
def list() -> None:
    """
    List all installed AST providers.

    Displays provider information including:
    - Provider name
    - Supported languages
    - Priority level
    - Version
    - Package source
    """
    console.print("\n[bold cyan]Discovering AST Providers...[/bold cyan]\n")

    try:
        # Initialize registry and discover providers
        registry = ASTProviderRegistry()

        # Use asyncio to run async discovery
        import asyncio
        asyncio.run(registry.discover_providers())

        # Get all providers
        providers = registry.list_providers()

        if not providers:
            console.print("[yellow]No providers found.[/yellow]")
            console.print("\n[dim]Install providers with:[/dim] warden providers install <language>")
            return

        # Create rich table
        table = Table(
            title="Installed AST Providers",
            show_header=True,
            header_style="bold magenta"
        )

        table.add_column("Provider", style="cyan", no_wrap=True)
        table.add_column("Languages", style="green")
        table.add_column("Priority", style="yellow")
        table.add_column("Version", style="blue")
        table.add_column("Source", style="dim")

        for metadata in sorted(providers, key=lambda m: m.priority.value):
            # Format languages
            languages = ", ".join(lang.value for lang in metadata.supported_languages)

            # Format priority
            priority_display = f"{metadata.priority.name} ({metadata.priority.value})"

            # Determine source
            source = "built-in" if metadata.name in ["python-native", "tree-sitter"] else "PyPI"

            table.add_row(
                metadata.name,
                languages,
                priority_display,
                metadata.version,
                source
            )

        console.print(table)
        console.print(f"\n[dim]Total providers:[/dim] {len(providers)}\n")

    except Exception as e:
        logger.error("provider_list_failed", error=str(e))
        console.print(f"[red]Failed to list providers: {e}[/red]")
        raise typer.Exit(code=1)


@app.command()
def install(
    provider: str = typer.Argument(..., help="Provider name or language (e.g., 'java', 'typescript')")
) -> None:
    """
    Install an AST provider from PyPI.

    Args:
        provider: Language name (e.g., 'java') or full package name

    Example:
        warden providers install java
        warden providers install warden-ast-java
    """
    # Map short name to package name
    package_name = PROVIDER_MAP.get(provider.lower(), provider)

    # If user provided warden-ast-* directly, use it
    if provider.startswith('warden-ast-'):
        package_name = provider

    console.print(f"\n[cyan]Installing {package_name}...[/cyan]\n")

    try:
        # Run pip install
        result = subprocess.run(
            [sys.executable, '-m', 'pip', 'install', package_name],
            capture_output=True,
            text=True,
            timeout=300  # 5 minutes timeout
        )

        if result.returncode == 0:
            console.print(Panel.fit(
                f"[green]Successfully installed {package_name}[/green]\n\n"
                f"[dim]Verify installation:[/dim]\n"
                f"  warden providers list\n"
                f"  warden providers test {provider}",
                title="Installation Complete",
                border_style="green"
            ))
            logger.info("provider_installed", package=package_name)
        else:
            # Installation failed
            console.print(f"[red]Failed to install {package_name}[/red]\n")
            console.print("[dim]Error details:[/dim]")
            console.print(result.stderr)
            logger.error("provider_install_failed", package=package_name, error=result.stderr)
            raise typer.Exit(code=1)

    except subprocess.TimeoutExpired:
        console.print(f"[red]Installation timed out for {package_name}[/red]")
        logger.error("provider_install_timeout", package=package_name)
        raise typer.Exit(code=1)
    except Exception as e:
        console.print(f"[red]Installation error: {e}[/red]")
        logger.error("provider_install_exception", package=package_name, error=str(e))
        raise typer.Exit(code=1)


@app.command()
def remove(
    provider: str = typer.Argument(..., help="Provider name or language to remove"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt")
) -> None:
    """
    Remove an AST provider.

    Args:
        provider: Language name (e.g., 'java') or full package name
        yes: Skip confirmation prompt

    Example:
        warden providers remove java
        warden providers remove java --yes
    """
    # Map short name to package name
    package_name = PROVIDER_MAP.get(provider.lower(), provider)

    # If user provided warden-ast-* directly, use it
    if provider.startswith('warden-ast-'):
        package_name = provider

    # Confirmation prompt
    if not yes:
        confirm = typer.confirm(f"Remove {package_name}?")
        if not confirm:
            console.print("[yellow]Removal cancelled.[/yellow]")
            return

    console.print(f"\n[cyan]Removing {package_name}...[/cyan]\n")

    try:
        # Run pip uninstall
        result = subprocess.run(
            [sys.executable, '-m', 'pip', 'uninstall', '-y', package_name],
            capture_output=True,
            text=True,
            timeout=60  # 1 minute timeout
        )

        if result.returncode == 0:
            console.print(f"[green]Successfully removed {package_name}[/green]")
            logger.info("provider_removed", package=package_name)
        else:
            # Removal failed
            console.print(f"[red]Failed to remove {package_name}[/red]\n")
            console.print("[dim]Error details:[/dim]")
            console.print(result.stderr)
            logger.error("provider_remove_failed", package=package_name, error=result.stderr)
            raise typer.Exit(code=1)

    except subprocess.TimeoutExpired:
        console.print(f"[red]Removal timed out for {package_name}[/red]")
        logger.error("provider_remove_timeout", package=package_name)
        raise typer.Exit(code=1)
    except Exception as e:
        console.print(f"[red]Removal error: {e}[/red]")
        logger.error("provider_remove_exception", package=package_name, error=str(e))
        raise typer.Exit(code=1)


@app.command()
def test(
    language: str = typer.Argument(..., help="Language to test provider for (e.g., 'python', 'java')")
) -> None:
    """
    Test if a language provider is available and functional.

    Args:
        language: Programming language name

    Example:
        warden providers test python
        warden providers test java
    """
    console.print(f"\n[cyan]Testing provider for {language}...[/cyan]\n")

    try:
        # Parse language enum
        try:
            lang = CodeLanguage(language.lower())
        except ValueError:
            console.print(f"[red]Unknown language: {language}[/red]\n")
            console.print("[dim]Supported languages:[/dim]")
            for code_lang in CodeLanguage:
                if code_lang != CodeLanguage.UNKNOWN:
                    console.print(f"  - {code_lang.value}")
            raise typer.Exit(code=1)

        # Initialize registry and discover providers
        registry = ASTProviderRegistry()

        # Use asyncio to run async discovery
        import asyncio
        asyncio.run(registry.discover_providers())

        # Get provider for language
        provider = registry.get_provider(lang)

        if provider:
            # Provider found - validate it
            is_valid = asyncio.run(provider.validate())

            if is_valid:
                console.print(Panel.fit(
                    f"[green]Provider available for {language}[/green]\n\n"
                    f"[dim]Provider:[/dim] {provider.metadata.name}\n"
                    f"[dim]Priority:[/dim] {provider.metadata.priority.name} ({provider.metadata.priority.value})\n"
                    f"[dim]Version:[/dim] {provider.metadata.version}\n"
                    f"[dim]Status:[/dim] Ready",
                    title="Provider Test - PASSED",
                    border_style="green"
                ))
                logger.info("provider_test_passed", language=language, provider=provider.metadata.name)
            else:
                console.print(Panel.fit(
                    f"[yellow]Provider found but not functional for {language}[/yellow]\n\n"
                    f"[dim]Provider:[/dim] {provider.metadata.name}\n"
                    f"[dim]Status:[/dim] Validation failed",
                    title="Provider Test - FAILED",
                    border_style="yellow"
                ))
                logger.warning("provider_test_validation_failed", language=language, provider=provider.metadata.name)
                raise typer.Exit(code=1)
        else:
            # No provider found
            console.print(Panel.fit(
                f"[red]No provider available for {language}[/red]\n\n"
                f"[dim]Install one with:[/dim]\n"
                f"  warden providers install {language}",
                title="Provider Test - NOT FOUND",
                border_style="red"
            ))
            logger.warning("provider_test_not_found", language=language)
            raise typer.Exit(code=1)

    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]Provider test error: {e}[/red]")
        logger.error("provider_test_exception", language=language, error=str(e))
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
