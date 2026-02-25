"""
Config Commands for Warden CLI

Provides commands for viewing and modifying Warden configuration:
- warden config list: Show all configuration
- warden config get <key>: Get a specific value (dot notation)
- warden config set <key> <value>: Set a specific value

Chaos Engineering Principles:
- Fail Fast: Validate inputs early, clear error messages
- Idempotent: Safe to run multiple times
- Observable: Structured output, JSON support
- Defensive: Handle all error cases gracefully
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import typer
import yaml
from rich.console import Console
from rich.tree import Tree

from warden.llm.types import LlmProvider

console = Console()

# Create Typer app for config subcommands
config_app = typer.Typer(
    name="config",
    help="View and modify Warden configuration",
    no_args_is_help=True,
)

# Sub-app for LLM helpers
llm_app = typer.Typer(name="llm", help="Manage LLM provider configuration")
config_app.add_typer(llm_app, name="llm")


# =============================================================================
# Constants
# =============================================================================

CONFIG_PATHS = [
    Path(".warden/config.yaml"),
    Path("warden.yaml"),
]

VALID_LLM_PROVIDERS = [p.value for p in LlmProvider]


# =============================================================================
# Helper Functions
# =============================================================================


def _find_config_path() -> Path | None:
    """
    Find the Warden config file.

    Returns:
        Path to config file or None if not found
    """
    for path in CONFIG_PATHS:
        if path.exists():
            return path
    return None


def _load_config() -> tuple[dict, Path]:
    """
    Load Warden configuration.

    Returns:
        Tuple of (config dict, config path)
    Raises:
        typer.Exit: If config not found
    """
    config_path = _find_config_path()
    if not config_path:
        console.print("[red]Error:[/red] Warden config not found.")
        console.print("[dim]Run 'warden init' to initialize the project.[/dim]")
        raise typer.Exit(1)

    try:
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}
        return config, config_path
    except yaml.YAMLError as e:
        console.print(f"[red]Error parsing config:[/red] {e}")
        raise typer.Exit(1)
    except PermissionError:
        console.print(f"[red]Permission denied:[/red] Cannot read {config_path}")
        raise typer.Exit(1)


def _save_config(config: dict, config_path: Path) -> None:
    """
    Save configuration to file.

    Args:
        config: Configuration dictionary
        config_path: Path to save to
    """
    try:
        with open(config_path, "w") as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)
    except PermissionError:
        console.print(f"[red]Permission denied:[/red] Cannot write to {config_path}")
        raise typer.Exit(1)


def _get_nested_value(data: dict, key: str) -> Any:
    """
    Get value from nested dict using dot notation.

    Args:
        data: Dictionary to search
        key: Dot-notation key (e.g., "llm.provider")

    Returns:
        Value at key or None if not found
    """
    keys = key.split(".")
    current = data

    for k in keys:
        if isinstance(current, dict) and k in current:
            current = current[k]
        else:
            return None

    return current


def _set_nested_value(data: dict, key: str, value: Any) -> None:
    """
    Set value in nested dict using dot notation.

    Args:
        data: Dictionary to modify
        key: Dot-notation key (e.g., "llm.provider")
        value: Value to set
    """
    keys = key.split(".")
    current = data

    # Navigate to parent, creating dicts as needed
    for k in keys[:-1]:
        if k not in current or not isinstance(current[k], dict):
            current[k] = {}
        current = current[k]

    # Set the final value
    current[keys[-1]] = value


def _validate_value(key: str, value: str) -> Any:
    """
    Validate and convert value based on key.

    Args:
        key: Configuration key
        value: String value to validate

    Returns:
        Converted value
    Raises:
        typer.Exit: If validation fails
    """
    # LLM provider validation
    if key == "llm.provider":
        if value not in VALID_LLM_PROVIDERS:
            console.print(f"[red]Invalid provider:[/red] '{value}'")
            console.print(f"[dim]Valid providers: {', '.join(VALID_LLM_PROVIDERS)}[/dim]")
            raise typer.Exit(1)
        return value

    # Boolean fields
    bool_keys = [
        "settings.fail_fast",
        "settings.use_llm",
        "settings.use_local_llm",
        "settings.enable_classification",
        "semantic_search.enabled",
    ]
    if key in bool_keys:
        if value.lower() in ("true", "1", "yes", "on"):
            return True
        elif value.lower() in ("false", "0", "no", "off"):
            return False
        else:
            console.print(f"[red]Invalid boolean:[/red] '{value}'")
            console.print("[dim]Use: true/false, yes/no, 1/0[/dim]")
            raise typer.Exit(1)

    # Integer fields
    int_keys = ["llm.timeout", "llm.max_tokens"]
    if key in int_keys:
        try:
            return int(value)
        except ValueError:
            console.print(f"[red]Invalid integer:[/red] '{value}'")
            raise typer.Exit(1)

    # Mode validation
    if key == "settings.mode":
        valid_modes = ["vibe", "normal", "strict"]
        if value not in valid_modes:
            console.print(f"[red]Invalid mode:[/red] '{value}'")
            console.print(f"[dim]Valid modes: {', '.join(valid_modes)}[/dim]")
            raise typer.Exit(1)
        return value

    # Default: return as string
    return value


def _build_config_tree(data: dict, tree: Tree, prefix: str = "") -> None:
    """
    Build Rich tree from config dict.

    Args:
        data: Configuration dictionary
        tree: Rich Tree to add to
        prefix: Key prefix for dot notation
    """
    for key, value in data.items():
        full_key = f"{prefix}{key}" if prefix else key

        if isinstance(value, dict):
            branch = tree.add(f"[cyan]{key}[/cyan]")
            _build_config_tree(value, branch, f"{full_key}.")
        elif isinstance(value, list):
            branch = tree.add(f"[cyan]{key}[/cyan]: [dim][list][/dim]")
            for i, item in enumerate(value):
                if isinstance(item, dict):
                    sub_branch = branch.add(f"[dim][{i}][/dim]")
                    _build_config_tree(item, sub_branch, f"{full_key}[{i}].")
                else:
                    branch.add(f"[green]{item}[/green]")
        else:
            # Color based on type
            if isinstance(value, bool):
                val_str = f"[yellow]{value}[/yellow]"
            elif isinstance(value, (int, float)):
                val_str = f"[magenta]{value}[/magenta]"
            elif value is None:
                val_str = "[dim]null[/dim]"
            else:
                val_str = f"[green]{value}[/green]"
            tree.add(f"[cyan]{key}[/cyan]: {val_str}")


# =============================================================================
# Commands
# =============================================================================


@config_app.command(name="list")
def config_list(
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
) -> None:
    """
    Show all Warden configuration.

    Examples:
        warden config list
        warden config list --json
    """
    config, config_path = _load_config()

    if json_output:
        import json

        console.print(json.dumps(config, indent=2))
        return

    # Build tree view
    tree = Tree(f"[bold blue]📋 Warden Config[/bold blue] [dim]({config_path})[/dim]")
    _build_config_tree(config, tree)
    console.print(tree)


@config_app.command(name="get")
def config_get(
    key: str = typer.Argument(..., help="Config key (dot notation, e.g., 'llm.provider')"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
) -> None:
    """
    Get a specific configuration value.

    Examples:
        warden config get llm.provider
        warden config get settings.mode
        warden config get frames
    """
    config, _ = _load_config()

    value = _get_nested_value(config, key)

    if value is None:
        console.print(f"[yellow]Key not found:[/yellow] {key}")
        raise typer.Exit(1)

    if json_output:
        import json

        console.print(json.dumps(value, indent=2) if isinstance(value, (dict, list)) else json.dumps(value))
        return

    # Pretty print based on type
    if isinstance(value, dict):
        tree = Tree(f"[cyan]{key}[/cyan]")
        _build_config_tree(value, tree)
        console.print(tree)
    elif isinstance(value, list):
        console.print(f"[cyan]{key}[/cyan]:")
        for item in value:
            console.print(f"  [green]- {item}[/green]")
    else:
        console.print(f"[cyan]{key}[/cyan]: [green]{value}[/green]")


@config_app.command(name="set")
def config_set(
    key: str = typer.Argument(..., help="Config key (dot notation, e.g., 'llm.provider')"),
    value: str = typer.Argument(..., help="Value to set"),
) -> None:
    """
    Set a configuration value.

    Examples:
        warden config set llm.provider claude_code
        warden config set llm.provider anthropic
        warden config set settings.mode strict
        warden config set settings.fail_fast true
    """
    config, config_path = _load_config()

    # Get old value for display
    old_value = _get_nested_value(config, key)

    # Validate and convert value
    validated_value = _validate_value(key, value)

    # Set the new value
    _set_nested_value(config, key, validated_value)

    # SMART UPDATE: If provider changed, update models too
    if key == "llm.provider":
        _update_provider_models(config, validated_value)
        console.print(f"[dim]→ Updated model fields for {validated_value}[/dim]")

    # Save config
    _save_config(config, config_path)

    # Show result
    if old_value is not None:
        console.print(f"[green]✓[/green] Updated [cyan]{key}[/cyan]:")
        console.print(f"  [dim]Old:[/dim] {old_value}")
        console.print(f"  [bold]New:[/bold] {validated_value}")
    else:
        console.print(f"[green]✓[/green] Set [cyan]{key}[/cyan]: {validated_value}")

    # Provider-specific hints
    if key == "llm.provider":
        _print_provider_hint(validated_value)


def _update_provider_models(config: dict, provider: str) -> None:
    """
    Update model fields when provider changes.

    Args:
        config: Configuration dictionary
        provider: New provider name
    """
    # Import here to avoid circular dependency
    from warden.llm.config import DEFAULT_MODELS
    from warden.llm.types import LlmProvider

    try:
        provider_enum = LlmProvider(provider)
        default_model = DEFAULT_MODELS.get(provider_enum)

        if default_model and "llm" in config:
            config["llm"]["model"] = default_model
            config["llm"]["smart_model"] = default_model

            # Fast model logic
            if provider == "ollama":
                config["llm"]["fast_model"] = "qwen2.5-coder:3b"
            elif provider == "claude_code":
                # Claude Code: placeholder model (actual model set in claude config)
                config["llm"]["fast_model"] = "claude-code-default"
            else:
                # Other providers: use ollama for fast tier if available
                config["llm"]["fast_model"] = "qwen2.5-coder:3b"
    except (ValueError, KeyError):
        # Invalid provider or missing config - skip update
        pass


def _print_provider_hint(provider: str) -> None:
    """Print helpful hints after changing provider."""
    hints = {
        "claude_code": (
            "[dim]💡 Claude Code uses your local Claude subscription.\n"
            "   - Ensure 'claude' CLI is installed and authenticated\n"
            "   - Model selection: Run 'claude config' to choose Sonnet/Opus/Haiku[/dim]"
        ),
        "ollama": ("[dim]💡 Ollama runs locally. Ensure Ollama is running:\n   ollama serve[/dim]"),
        "anthropic": ("[dim]💡 Set your API key:\n   export ANTHROPIC_API_KEY=your-key[/dim]"),
        "openai": ("[dim]💡 Set your API key:\n   export OPENAI_API_KEY=your-key[/dim]"),
        "groq": ("[dim]💡 Set your API key:\n   export GROQ_API_KEY=your-key[/dim]"),
        "azure_openai": (
            "[dim]💡 Set Azure credentials:\n"
            "   export AZURE_OPENAI_API_KEY=your-key\n"
            "   export AZURE_OPENAI_ENDPOINT=your-endpoint[/dim]"
        ),
    }

    if provider in hints:
        console.print()
        console.print(hints[provider])


# =============================================================================
# Shortcut: warden config (without subcommand) shows list
# =============================================================================


@config_app.callback(invoke_without_command=True)
def config_callback(ctx: typer.Context) -> None:
    """
    View and modify Warden configuration.

    Without subcommand, shows the full configuration (same as 'warden config list').
    """
    if ctx.invoked_subcommand is None:
        config_list(json_output=False)


# =============================================================================
# LLM Subcommands
# =============================================================================


def _provider_key_var(provider: str) -> str | None:
    mapping = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "groq": "GROQ_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "gemini": "GEMINI_API_KEY",
    }
    if provider == "azure":
        return "AZURE_OPENAI_API_KEY"
    return mapping.get(provider)


def _env_present(name: str) -> bool:
    import os

    return bool(os.environ.get(name))


def _provider_health(provider: str) -> str:
    """Return a health indicator string for a provider."""
    import shutil

    if provider == "ollama":
        import urllib.request as req
        from urllib.error import URLError

        host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        try:
            with req.urlopen(f"{host}/api/tags", timeout=2) as r:
                return "[green]running[/green]" if r.status == 200 else f"[yellow]http {r.status}[/yellow]"
        except URLError:
            return "[red]unreachable[/red]"
    elif provider == "claude_code":
        return "[green]found[/green]" if shutil.which("claude") else "[red]missing[/red]"
    elif provider == "codex":
        return "[green]found[/green]" if shutil.which("codex") else "[red]missing[/red]"
    else:
        key_var = _provider_key_var(provider)
        if key_var:
            return "[green]key present[/green]" if _env_present(key_var) else "[red]key missing[/red]"
    return "[dim]unknown[/dim]"


@llm_app.command("status")
def llm_status() -> None:
    """Show smart and fast tier LLM configuration."""
    config, config_path = _load_config()
    llm = config.get("llm", {})

    smart_provider = llm.get("provider") or os.environ.get("WARDEN_LLM_PROVIDER") or "unknown"
    smart_model = llm.get("smart_model") or llm.get("model") or "—"
    fast_providers = llm.get("fast_tier_providers") or []
    fast_model = llm.get("fast_model") or "—"

    from rich.table import Table

    table = Table(show_header=True, header_style="bold blue", box=None, padding=(0, 2))
    table.add_column("Tier", style="bold")
    table.add_column("Provider")
    table.add_column("Model", style="cyan")
    table.add_column("Health")

    table.add_row(
        "smart",
        f"[green]{smart_provider}[/green]",
        smart_model,
        _provider_health(smart_provider),
    )
    if fast_providers:
        for i, fp in enumerate(fast_providers):
            table.add_row(
                "fast" if i == 0 else "",
                f"[yellow]{fp}[/yellow]",
                fast_model if i == 0 else "—",
                _provider_health(fp),
            )
    else:
        table.add_row("fast", "[dim]none[/dim]", "—", "[dim]—[/dim]")

    console.print()
    console.print(f"[bold]LLM Configuration[/bold]  [dim]{config_path}[/dim]")
    console.print(table)
    console.print()
    console.print("[dim]Change:  warden config llm smart <provider> [--model <model>][/dim]")
    console.print("[dim]         warden config llm fast <provider>  [--model <model>][/dim]")


@llm_app.command("smart")
def llm_smart(
    provider: str = typer.Argument(..., help="Smart tier provider (e.g., ollama, anthropic, claude_code, groq)"),
    model: str | None = typer.Option(None, "--model", "-m", help="Override model name"),
) -> None:
    """Set the smart tier (primary) LLM provider and model.

    Examples:
        warden config llm smart ollama
        warden config llm smart ollama --model qwen2.5-coder:7b
        warden config llm smart anthropic --model claude-opus-4-5-20251001
        warden config llm smart groq
    """
    from warden.llm.config import DEFAULT_MODELS
    from warden.llm.types import LlmProvider

    provider = provider.strip().lower()
    valid = [p.value for p in LlmProvider]
    if provider not in valid:
        console.print(f"[red]Invalid provider:[/red] {provider}")
        console.print(f"[dim]Valid: {', '.join(valid)}[/dim]")
        raise typer.Exit(1)

    config, config_path = _load_config()
    llm = config.setdefault("llm", {})

    old_provider = llm.get("provider", "—")
    old_model = llm.get("smart_model") or llm.get("model") or "—"

    try:
        provider_enum = LlmProvider(provider)
        resolved_model = model or DEFAULT_MODELS.get(provider_enum, "")
    except ValueError:
        resolved_model = model or ""

    llm["provider"] = provider
    if resolved_model:
        llm["smart_model"] = resolved_model
        llm["model"] = resolved_model

    _save_config(config, config_path)

    console.print(f"[green]✓[/green] Smart tier updated:")
    console.print(f"  Provider  [dim]{old_provider}[/dim] → [green]{provider}[/green]")
    console.print(f"  Model     [dim]{old_model}[/dim] → [cyan]{resolved_model or '—'}[/cyan]")
    _print_provider_hint(provider)


@llm_app.command("fast")
def llm_fast(
    provider: str = typer.Argument(..., help="Fast tier provider (e.g., ollama, groq, none)"),
    model: str | None = typer.Option(None, "--model", "-m", help="Override model name"),
) -> None:
    """Set the fast tier LLM provider and model.

    Pass 'none' to disable the fast tier entirely.

    Examples:
        warden config llm fast ollama
        warden config llm fast ollama --model qwen2.5-coder:7b
        warden config llm fast groq
        warden config llm fast none
    """
    from warden.llm.config import DEFAULT_MODELS
    from warden.llm.types import LlmProvider

    provider = provider.strip().lower()

    config, config_path = _load_config()
    llm = config.setdefault("llm", {})
    old_fast = llm.get("fast_tier_providers") or []
    old_model = llm.get("fast_model") or "—"

    if provider == "none":
        llm["fast_tier_providers"] = []
        llm["fast_model"] = ""
        _save_config(config, config_path)
        console.print("[green]✓[/green] Fast tier disabled.")
        return

    valid = [p.value for p in LlmProvider]
    if provider not in valid:
        console.print(f"[red]Invalid provider:[/red] {provider}")
        console.print(f"[dim]Valid: {', '.join(valid)} or 'none'[/dim]")
        raise typer.Exit(1)

    try:
        provider_enum = LlmProvider(provider)
        resolved_model = model or DEFAULT_MODELS.get(provider_enum, "")
    except ValueError:
        resolved_model = model or ""

    llm["fast_tier_providers"] = [provider]
    if resolved_model:
        llm["fast_model"] = resolved_model

    _save_config(config, config_path)

    console.print(f"[green]✓[/green] Fast tier updated:")
    console.print(f"  Provider  [dim]{old_fast}[/dim] → [yellow]{provider}[/yellow]")
    console.print(f"  Model     [dim]{old_model}[/dim] → [cyan]{resolved_model or '—'}[/cyan]")
    _print_provider_hint(provider)


@llm_app.command("edit")
def llm_edit() -> None:
    """Open interactive TUI to configure Local and CI/CD LLM providers.

    Local tab  — all providers (Ollama, Claude Code, Codex, APIs…)
    CI/CD tab  — API-only providers (no CLI tools, no local servers)

    Examples:
        warden config llm edit
    """
    from ._llm_ui import run_llm_config_ui

    config, config_path = _load_config()
    llm = config.get("llm", {})
    ci_llm = llm.get("ci", {})

    current = {
        # local
        "local_smart_provider": llm.get("provider", "ollama"),
        "local_smart_model": llm.get("smart_model") or llm.get("model") or "",
        "local_fast_provider": (llm.get("fast_tier_providers") or ["none"])[0],
        "local_fast_model": llm.get("fast_model") or "",
        # ci
        "ci_smart_provider": ci_llm.get("provider", "groq"),
        "ci_smart_model": ci_llm.get("smart_model") or ci_llm.get("model") or "",
        "ci_fast_provider": (ci_llm.get("fast_tier_providers") or ["groq"])[0],
        "ci_fast_model": ci_llm.get("fast_model") or "",
    }

    result = run_llm_config_ui(current)

    if result is None or not result.saved:
        console.print("[yellow]Cancelled — no changes saved.[/yellow]")
        return

    # ── persist local ──────────────────────────────────────────────────────
    llm["provider"] = result.local_smart_provider
    llm["smart_model"] = result.local_smart_model
    llm["model"] = result.local_smart_model
    llm["fast_tier_providers"] = [] if result.local_fast_provider == "none" else [result.local_fast_provider]
    llm["fast_model"] = result.local_fast_model

    # ── persist ci ────────────────────────────────────────────────────────
    ci_section: dict = {}
    ci_section["provider"] = result.ci_smart_provider
    ci_section["smart_model"] = result.ci_smart_model
    ci_section["model"] = result.ci_smart_model
    ci_section["fast_tier_providers"] = [] if result.ci_fast_provider == "none" else [result.ci_fast_provider]
    ci_section["fast_model"] = result.ci_fast_model
    llm["ci"] = ci_section

    _save_config(config, config_path)

    console.print(f"[green]✓[/green] Saved to [dim]{config_path}[/dim]")
    console.print()
    console.print("[bold]Local[/bold]")
    console.print(f"  Smart  [green]{result.local_smart_provider}[/green]  [cyan]{result.local_smart_model}[/cyan]")
    _fast_line(result.local_fast_provider, result.local_fast_model)
    console.print()
    console.print("[bold]CI / CD[/bold]")
    console.print(f"  Smart  [green]{result.ci_smart_provider}[/green]  [cyan]{result.ci_smart_model}[/cyan]")
    _fast_line(result.ci_fast_provider, result.ci_fast_model)


def _fast_line(provider: str, model: str) -> None:
    if provider == "none":
        console.print("  Fast   [dim]disabled[/dim]")
    else:
        console.print(f"  Fast   [yellow]{provider}[/yellow]  [cyan]{model}[/cyan]")


@llm_app.command("use")
def llm_use(
    provider: str = typer.Argument(
        ..., help="Provider name (e.g., ollama, anthropic, openai, azure, groq, deepseek, gemini, claude_code)"
    ),
) -> None:
    """Set active LLM provider and update default models."""
    provider = provider.strip().lower()
    if provider not in [p.value for p in LlmProvider] and provider not in ("claude_code",):
        console.print(f"[red]Invalid provider:[/red] {provider}")
        raise typer.Exit(1)

    config, config_path = _load_config()
    _set_nested_value(config, "llm.provider", provider)
    _update_provider_models(config, provider)
    _save_config(config, config_path)
    console.print(f"[green]✓[/green] Using provider: [cyan]{provider}[/cyan]")


@llm_app.command("test")
def llm_test() -> None:
    """Validate provider configuration (keys/endpoints)."""
    import json as _json
    import urllib.request as req
    from urllib.error import URLError

    config, _ = _load_config()
    provider = config.get("llm", {}).get("provider", "unknown")

    results: dict[str, str] = {}
    if provider == "ollama":
        host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        try:
            with req.urlopen(f"{host}/api/tags", timeout=3) as r:
                if r.status == 200:
                    results["ollama"] = "ok"
                else:
                    results["ollama"] = f"http {r.status}"
        except URLError as e:
            results["ollama"] = f"error: {e.reason}"
    elif provider == "claude_code":
        import shutil

        results["claude_code"] = "found" if shutil.which("claude") else "missing"
    elif provider == "codex":
        import shutil

        results["codex"] = "found" if shutil.which("codex") else "missing"
    else:
        key_var = _provider_key_var(provider)
        if key_var:
            results[provider] = "key_present" if _env_present(key_var) else "key_missing"
        else:
            results[provider] = "unknown"

    console.print("[bold blue]🔎 LLM Test[/bold blue]")
    for k, v in results.items():
        status = "[green]OK[/green]" if v in ("ok", "found", "key_present") else f"[yellow]{v}[/yellow]"
        console.print(f"{k}: {status}")
