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


@rules_app.command(name="refine")
def refine_command(
    path: Path = typer.Option(Path("."), "--path", "-p", help="Project directory (default: cwd)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show proposed changes without writing"),
    rule_id: list[str] = typer.Option([], "--rule", "-r", help="Limit to specific rule IDs (repeatable)"),
) -> None:
    """Refine AI rule context fields by analyzing recent scan findings for false positives.

    Reads the findings cache from the last scan, classifies each finding using
    the configured LLM, and appends acceptable-pattern guidance to the context
    field of rules that produced false positives.

    Examples:
        warden rules refine
        warden rules refine --dry-run
        warden rules refine --rule no-bare-except --rule no-hardcoded-secrets
        warden rules refine --path /path/to/project
    """
    root = path.resolve()
    warden_dir = root / ".warden"

    if not warden_dir.exists():
        console.print("[red]Error: Warden not initialized. Run 'warden init' first.[/red]")
        raise typer.Exit(1)

    console.print("\n[bold cyan]⚙  Warden Rules Refine[/bold cyan]")

    llm_service = _load_llm_service()
    if llm_service is None:
        raise typer.Exit(1)

    asyncio.run(_refine_async(root, llm_service, list(rule_id) or None, dry_run))


async def _refine_async(
    root: Path,
    llm_service,
    rule_ids: list[str] | None,
    dry_run: bool,
) -> None:
    from rich.table import Table

    from warden.rules.application.rule_refiner import refine_rules

    try:
        result = await refine_rules(
            project_path=root,
            llm_service=llm_service,
            rule_ids=rule_ids,
            dry_run=dry_run,
        )
    except Exception as exc:
        console.print(f"[red]Refine failed: {exc}[/red]")
        raise typer.Exit(1)

    # Summary table
    if result.analyzed > 0:
        table = Table(title="Refinement Results", show_lines=True)
        table.add_column("Rule ID", style="cyan")
        table.add_column("Verdict", style="green")
        table.add_column("Pattern")

        for upd in result.updates:
            table.add_row(upd["rule_id"], "false_positive", upd["pattern"])

        console.print(table)

    # Status line
    console.print(
        f"\nAnalyzed: [bold]{result.analyzed}[/bold]  "
        f"Real: [bold]{result.skipped_real}[/bold]  "
        f"Duplicates skipped: [bold]{result.skipped_duplicate}[/bold]"
    )

    if result.updates:
        if dry_run:
            console.print(f"\n[yellow][dry-run] Would update {len(result.updates)} rules[/yellow]")
            for upd in result.updates:
                console.print(f"\n  [bold]{upd['rule_id']}[/bold] proposed context addition:")
                console.print(f"  [dim]Acceptable: {upd['pattern']} — {upd['reason']}[/dim]")
        else:
            console.print(f"\n[green]✓ Updated context for {len(result.updates)} rules[/green]")
    else:
        console.print("\n[dim]No context updates needed.[/dim]")


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
