import os
import sys
from pathlib import Path

import typer
import yaml

from warden.cli.commands.init_helpers import configure_vector_db
from warden.cli.commands.init_steps import (
    configure_llm_and_env,
    detect_project,
    generate_config,
    generate_scaffolds,
    run_post_setup,
    select_mode,
)

from rich.console import Console

console = Console()


def init_command(
    ctx: typer.Context,
    force: bool = typer.Option(False, "--force", "-f", help="Force initialization even if config exists"),
    mode: str = typer.Option("normal", "--mode", "-m", help="Initialization mode (vibe, normal, strict)"),
    ci: bool = typer.Option(False, "--ci", help="Generate GitHub Actions CI workflow"),
    skip_mcp: bool = typer.Option(False, "--skip-mcp", help="Skip MCP server registration"),
    agent: bool = typer.Option(
        True,
        "--agent/--no-agent",
        help="Configure agent files (Claude/Cursor) and register MCP server",
    ),
    baseline: bool = typer.Option(
        True,
        "--baseline/--no-baseline",
        help="Create baseline from current issues",
    ),
    intel: bool = typer.Option(
        True,
        "--intel/--no-intel",
        help="Generate project intelligence for CI optimization",
    ),
    grammars: bool = typer.Option(
        True,
        "--grammars/--no-grammars",
        help="Install missing tree-sitter grammars",
    ),
    provider: str | None = typer.Option(
        None,
        "--provider",
        "-p",
        help=(
            "LLM provider for non-interactive/CI use. "
            "Options: ollama, anthropic, openai, groq, azure, deepseek, gemini. "
            "Note: claude_code is excluded from CI usage."
        ),
    ),
) -> None:
    """
    Initialize Warden in the current directory with Smart Detection.
    """
    console.print("[bold blue]🛡️  Initializing Warden (Smart Mode)...[/bold blue]")

    warden_dir = Path(".warden")
    warden_dir.mkdir(parents=True, exist_ok=True)

    # Mark incomplete — if init crashes, next run can detect and warn
    incomplete_marker = warden_dir / ".incomplete"
    if incomplete_marker.exists():
        console.print("[yellow]⚠ Previous init was incomplete. Re-running...[/yellow]")
    incomplete_marker.touch()  # Always mark, even re-init

    is_interactive = sys.stdin.isatty() and os.environ.get("WARDEN_NON_INTERACTIVE") != "true"

    # --- Step 1: Detect Project ---
    meta, context = detect_project(warden_dir)

    # --- Step 2: Mode Selection ---
    mode_choice, mode_config = select_mode(mode, is_interactive, meta)

    # Load existing config for defaults
    existing_config = {}
    config_path = warden_dir / "config.yaml"
    if config_path.exists():
        try:
            with open(config_path) as f:
                existing_config = yaml.safe_load(f) or {}
        except (FileNotFoundError, PermissionError, yaml.YAMLError):
            pass  # Use empty config as default

    # --- Step 3: LLM Config ---
    llm_config, provider, model = configure_llm_and_env(provider, existing_config, is_interactive)

    # --- Step 4: Vector Database ---
    vector_config = configure_vector_db()

    # --- Step 5: Generate Config ---
    config_path = generate_config(
        config_path=config_path,
        warden_dir=warden_dir,
        meta=meta,
        mode_choice=mode_choice,
        mode_config=mode_config,
        provider=provider,
        model=model,
        llm_config=llm_config,
        vector_config=vector_config,
        force=force,
        is_interactive=is_interactive,
        existing_config=existing_config,
    )

    # --- Steps 5.5 – 8: Scaffolds, ignore files, rules, config comments ---
    generate_scaffolds(warden_dir, config_path, meta)

    # --- Steps 9 – 16: Post-setup (semantic, agent, baseline, intel, CI, grammars, context) ---
    run_post_setup(
        config_path=config_path,
        meta=meta,
        llm_config=llm_config,
        context=context,
        agent=agent,
        skip_mcp=skip_mcp,
        baseline=baseline,
        intel=intel,
        ci=ci,
        force=force,
        is_interactive=is_interactive,
        grammars=grammars,
    )

    # Init completed (with possible warnings) — remove marker
    # Partial completion with warnings is still considered complete.
    try:
        incomplete_marker.unlink(missing_ok=True)
    except OSError:
        pass  # Best effort cleanup
