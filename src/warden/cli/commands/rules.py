"""Warden rules sub-commands.

Provides 'warden rules generate' for AI-powered rule scaffolding.
"""

import asyncio
from pathlib import Path

import typer
from rich.console import Console

console = Console()

rules_app = typer.Typer(name="rules", help="Manage Warden custom rules.", no_args_is_help=True)


@rules_app.command(name="generate")
def generate_command(
    path: Path = typer.Option(Path("."), "--path", "-p", help="Project directory (default: cwd)"),
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing llm_generated.yml"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print rules to terminal, do not write file"),
) -> None:
    """Generate AI rules for this project using LLM analysis.

    Detects the project language and framework, asks the configured LLM to
    produce type:ai rules, and writes them to .warden/rules/llm_generated.yml.

    Review the output and commit the file to your repository.
    On the next scan, the orchestrator loads the rules automatically.

    Examples:
        warden rules generate
        warden rules generate --force
        warden rules generate --dry-run
        warden rules generate --path /path/to/project
    """
    root = path.resolve()
    warden_dir = root / ".warden"

    if not warden_dir.exists():
        console.print("[red]Error: Warden not initialized. Run 'warden init' first.[/red]")
        raise typer.Exit(1)

    console.print("\n[bold cyan]⚙  Warden Rules Generate[/bold cyan]")

    llm_service = _load_llm_service()
    if llm_service is None:
        raise typer.Exit(1)

    if dry_run:
        asyncio.run(_dry_run_async(root, llm_service))
        return

    output_path = warden_dir / "rules" / "llm_generated.yml"
    if output_path.exists() and not force:
        console.print(
            f"[yellow]⚠  {output_path.relative_to(root)} already exists. "
            "Use --force to overwrite.[/yellow]"
        )
        raise typer.Exit(0)

    asyncio.run(_generate_async(root, llm_service, force))


def _load_llm_service():
    """Load and return LLM service, or None on failure."""
    try:
        from warden.llm.config import load_llm_config
        from warden.llm.factory import create_client

        llm_config = load_llm_config()
        if llm_config is None:
            console.print(
                "[red]Error: LLM not configured. Run 'warden config llm' to set up.[/red]"
            )
            return None

        service = create_client(llm_config.default_provider)
        if service:
            service.config = llm_config
        return service
    except Exception as exc:
        console.print(f"[red]Error loading LLM service: {exc}[/red]")
        return None


async def _generate_async(root: Path, llm_service, force: bool) -> None:
    from warden.rules.application.rule_generator import OUTPUT_FILENAME, generate_rules_for_project

    try:
        count = await generate_rules_for_project(root, llm_service, force=force)
    except ValueError as exc:
        console.print(f"[red]Rule generation failed: {exc}[/red]")
        raise typer.Exit(1)
    except Exception as exc:
        console.print(f"[red]Unexpected error: {exc}[/red]")
        raise typer.Exit(1)

    if count == -1:
        console.print("[yellow]Rules already exist. Use --force to overwrite.[/yellow]")
    else:
        output_path = root / ".warden" / "rules" / OUTPUT_FILENAME
        console.print(
            f"[green]✓ {count} kural oluşturuldu → {output_path}\n"
            "[dim]Review edip git commit edin.[/dim][/green]"
        )


async def _dry_run_async(root: Path, llm_service) -> None:
    from warden.analysis.application.discovery.framework_detector import detect_frameworks_async
    from warden.rules.application.rule_generator import (
        _JS_FRAMEWORKS,
        _PY_FRAMEWORKS,
        _RULE_GEN_PROMPT,
    )

    detection = await detect_frameworks_async(root)
    framework = detection.primary_framework.value if detection.primary_framework else "unknown"
    fw = framework.lower()
    language = (
        "python"
        if fw in _PY_FRAMEWORKS
        else ("javascript/typescript" if fw in _JS_FRAMEWORKS else "unknown")
    )

    prompt = _RULE_GEN_PROMPT.format(language=language, framework=framework)
    response = await llm_service.complete_async(
        prompt=prompt,
        system_prompt="You are a Warden rule definition generator. Output YAML only.",
    )
    raw: str = response.content if hasattr(response, "content") else str(response)
    console.print("[bold]Generated rules (dry-run — not written to disk):[/bold]\n")
    console.print(raw)
