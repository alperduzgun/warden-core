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
                config["llm"]["fast_model"] = "qwen2.5-coder:0.5b"
            elif provider == "claude_code":
                # Claude Code: placeholder model (actual model set in claude config)
                config["llm"]["fast_model"] = "claude-code-default"
            else:
                # Other providers: use ollama for fast tier if available
                config["llm"]["fast_model"] = "qwen2.5-coder:0.5b"
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
