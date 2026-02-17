"""
CI Config Command

Stand-alone CLI command to generate or update CI/CD workflow files
independently of ``warden init``.

Usage examples::

    warden ci-config                                    # Interactive
    warden ci-config --ci-provider github --llm-provider groq
    warden ci-config --ci-provider gitlab --llm-provider ollama \\
                     --fast-model qwen2.5-coder:0.5b --force
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import typer
from rich.console import Console

from warden.cli.commands.init_helpers import (
    CI_PROVIDERS,
    LLM_PROVIDERS,
    configure_ci_workflow,
    select_ci_provider,
    select_llm_provider,
)

console = Console()

# Mapping from human-friendly id to CI_PROVIDERS key
_CI_ID_TO_KEY = {v["id"]: k for k, v in CI_PROVIDERS.items()}


def _resolve_ci_provider(ci_provider_id: str) -> dict | None:
    """Return CI_PROVIDERS entry for the given id, or None."""
    key = _CI_ID_TO_KEY.get(ci_provider_id.lower())
    return CI_PROVIDERS.get(key) if key else None


def _resolve_llm_provider(llm_provider_id: str) -> dict | None:
    """Return LLM_PROVIDERS entry for the given id, or None."""
    return next((v for v in LLM_PROVIDERS.values() if v["id"] == llm_provider_id.lower()), None)


def _build_llm_config(provider_info: dict, fast_model: str | None) -> dict:
    """Build the llm_config dict expected by configure_ci_workflow."""
    default_fast = fast_model or "qwen2.5-coder:0.5b"
    return {
        "provider": provider_info["id"],
        "model": provider_info.get("default_model", ""),
        "fast_model": default_fast,
    }


def ci_config_command(
    ci_provider: str | None = typer.Option(
        None,
        "--ci-provider",
        help="CI platform: github, gitlab. If omitted, prompts interactively.",
    ),
    llm_provider: str | None = typer.Option(
        None,
        "--llm-provider",
        help=(
            "Smart tier LLM provider for CI scans: "
            "groq, openai, anthropic, azure, deepseek, gemini, ollama. "
            "Note: claude_code is NOT supported in CI."
        ),
    ),
    fast_model: str | None = typer.Option(
        None,
        "--fast-model",
        help="Fast tier model override (default: qwen2.5-coder:0.5b via Ollama).",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Overwrite existing CI workflow files without prompting.",
    ),
) -> None:
    """
    Configure CI/CD workflow for Warden.

    Generates GitHub Actions or GitLab CI workflow files using the selected
    LLM provider. Can be run independently of ``warden init``.
    """
    console.print("[bold blue]CI/CD Workflow Configuration[/bold blue]")

    project_root = Path.cwd()

    # --- Resolve CI provider ---
    ci_provider_info: dict | None = None
    if ci_provider:
        ci_provider_info = _resolve_ci_provider(ci_provider)
        if not ci_provider_info:
            console.print(
                f"[red]Unknown CI provider: '{ci_provider}'. "
                f"Valid options: github, gitlab[/red]"
            )
            raise typer.Exit(code=1)
    else:
        # Interactive selection
        ci_provider_info = select_ci_provider()

    if ci_provider_info.get("id") == "skip":
        console.print("[dim]CI configuration skipped.[/dim]")
        return

    # --- Resolve LLM provider ---
    llm_provider_info: dict | None = None
    if llm_provider:
        llm_provider_info = _resolve_llm_provider(llm_provider)
        if not llm_provider_info:
            console.print(
                f"[red]Unknown LLM provider: '{llm_provider}'. "
                f"Valid options: ollama, anthropic, openai, groq, azure, deepseek, gemini[/red]"
            )
            raise typer.Exit(code=1)
        if not llm_provider_info.get("ci_supported", True):
            console.print(
                f"[red]Provider '{llm_provider}' is not supported in CI environments.[/red]"
            )
            raise typer.Exit(code=1)
    else:
        # Interactive selection with CI context (filters out claude_code)
        llm_provider_info = select_llm_provider()

    # --- Detect default branch ---
    branch = "main"
    try:
        branch = subprocess.check_output(
            ["git", "branch", "--show-current"], text=True, timeout=3
        ).strip() or "main"
    except (OSError, subprocess.TimeoutExpired, subprocess.CalledProcessError):
        pass

    # --- Check for existing files if not --force ---
    if not force and ci_provider_info["id"] == "github":
        existing = [
            project_root / ".github" / "workflows" / "warden-pr.yml",
            project_root / ".github" / "workflows" / "warden-nightly.yml",
            project_root / ".github" / "workflows" / "warden-release.yml",
        ]
        found = [p for p in existing if p.exists()]
        if found:
            console.print(
                f"[yellow]Existing CI workflow(s) found: "
                f"{', '.join(p.name for p in found)}[/yellow]"
            )
            console.print("[dim]Use --force to overwrite.[/dim]")
            raise typer.Exit(code=1)
    elif not force and ci_provider_info["id"] == "gitlab":
        existing_gl = project_root / ".gitlab-ci.yml"
        if existing_gl.exists():
            console.print("[yellow]Existing .gitlab-ci.yml found. Use --force to overwrite.[/yellow]")
            raise typer.Exit(code=1)

    # --- Generate workflows ---
    llm_config = _build_llm_config(llm_provider_info, fast_model)
    success = configure_ci_workflow(ci_provider_info, llm_config, project_root, branch)

    if success:
        console.print(
            f"\n[bold green]CI workflow configured:[/bold green] "
            f"{ci_provider_info['name']}"
        )
        console.print(
            f"  Provider: [cyan]{llm_provider_info['id']}[/cyan] (smart) + "
            f"[cyan]ollama[/cyan] (fast, {llm_config['fast_model']})"
        )
        if ci_provider_info["id"] == "github":
            console.print(
                "  Run [bold]git add .github/workflows/[/bold] to stage the files."
            )
        elif ci_provider_info["id"] == "gitlab":
            console.print("  Run [bold]git add .gitlab-ci.yml[/bold] to stage the file.")
    else:
        console.print("[red]CI workflow configuration failed.[/red]")
        raise typer.Exit(code=1)
