"""
Warden rules management commands.
Manage custom validation rules for your project.
"""

import asyncio
import sys
from pathlib import Path
from typing import Optional

import typer
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich import box

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from warden.rules.infrastructure.yaml_loader import RulesYAMLLoader
from warden.rules.application.rule_validator import CustomRuleValidator
from warden.rules.domain.models import CustomRule, ProjectRuleConfig
from warden.shared.infrastructure.logging import get_logger

app = typer.Typer()
console = Console()
logger = get_logger(__name__)


@app.command()
def validate(
    config_file: str = typer.Argument(..., help="Path to rules configuration file")
):
    """
    Validate rules configuration file.

    Checks YAML syntax, rule IDs, severity levels, and required fields.

    Example:
        warden rules validate .warden/rules.yaml
    """
    asyncio.run(validate_rules_config(config_file))


async def validate_rules_config(config_file: str):
    """Async validation logic for rules configuration."""
    config_path = Path(config_file)

    # Check if file exists
    if not config_path.exists():
        console.print(f"[red]Error:[/red] File not found: {config_file}")
        raise typer.Exit(code=1)

    console.print(Panel.fit(
        f"[bold cyan]Validating Rules Configuration[/bold cyan]\n"
        f"[dim]File:[/dim] {config_path}",
        title="Validation",
        border_style="cyan"
    ))

    # Load and validate YAML
    try:
        config = await RulesYAMLLoader.load_from_file(config_path)
    except FileNotFoundError as e:
        console.print(f"\n[red]File Error:[/red] {e}")
        raise typer.Exit(code=1)
    except ValueError as e:
        console.print(f"\n[red]Validation Error:[/red] {e}")
        raise typer.Exit(code=1)
    except yaml.YAMLError as e:
        console.print(f"\n[red]YAML Syntax Error:[/red] {e}")
        raise typer.Exit(code=1)
    except Exception as e:
        console.print(f"\n[red]Unexpected Error:[/red] {e}")
        raise typer.Exit(code=1)

    # Create validation summary table
    table = Table(title="Validation Summary", box=box.ROUNDED, show_header=False)
    table.add_column("Check", style="cyan bold", width=30)
    table.add_column("Status", style="white")

    # YAML syntax
    table.add_row("YAML Syntax", "[green]✓ Valid[/green]")

    # Project section
    if config.project_name:
        table.add_row("Project Name", f"[green]✓ {config.project_name}[/green]")
    else:
        table.add_row("Project Name", "[yellow]⚠ Missing[/yellow]")

    # Language
    if config.language:
        table.add_row("Language", f"[green]✓ {config.language}[/green]")
    else:
        table.add_row("Language", "[yellow]⚠ Missing[/yellow]")

    # Rules count
    total_rules = len(config.rules)
    enabled_rules = sum(1 for r in config.rules if r.enabled)
    disabled_rules = total_rules - enabled_rules
    table.add_row("Total Rules", f"[green]{total_rules}[/green]")
    table.add_row("Enabled Rules", f"[green]{enabled_rules}[/green]")
    table.add_row("Disabled Rules", f"[dim]{disabled_rules}[/dim]")

    # Check for duplicate rule IDs
    rule_ids = [r.id for r in config.rules]
    duplicates = [rid for rid in rule_ids if rule_ids.count(rid) > 1]
    if duplicates:
        table.add_row("Duplicate IDs", f"[red]✗ {set(duplicates)}[/red]")
    else:
        table.add_row("Duplicate IDs", "[green]✓ None[/green]")

    # Severity distribution
    severity_counts = {}
    for rule in config.rules:
        severity_counts[rule.severity.value] = severity_counts.get(rule.severity.value, 0) + 1

    for severity, count in severity_counts.items():
        color = {
            "critical": "red",
            "high": "yellow",
            "medium": "blue",
            "low": "dim"
        }.get(severity, "white")
        table.add_row(f"{severity.capitalize()} Severity", f"[{color}]{count}[/{color}]")

    # Blocker rules
    blocker_count = sum(1 for r in config.rules if r.is_blocker)
    if blocker_count > 0:
        table.add_row("Blocker Rules", f"[red bold]{blocker_count}[/red bold]")
    else:
        table.add_row("Blocker Rules", "[dim]0[/dim]")

    console.print("\n")
    console.print(table)

    # Check for issues
    has_errors = len(duplicates) > 0

    if has_errors:
        console.print("\n")
        console.print(Panel(
            "[red bold]Validation Failed[/red bold]\n"
            "[yellow]Fix the errors above and try again.[/yellow]",
            border_style="red"
        ))
        raise typer.Exit(code=1)
    else:
        console.print("\n")
        console.print(Panel(
            "[green bold]✓ Configuration is valid![/green bold]\n"
            f"[dim]All {total_rules} rule(s) are properly configured.[/dim]",
            border_style="green"
        ))
        raise typer.Exit(code=0)


@app.command()
def list(
    config: str = typer.Option(
        ".warden/rules.yaml",
        "--config",
        "-c",
        help="Rules config file"
    ),
    show_disabled: bool = typer.Option(
        False,
        "--show-disabled",
        help="Show disabled rules"
    ),
):
    """
    List all configured rules.

    Displays a table showing rule IDs, types, severity, and status.

    Example:
        warden rules list
        warden rules list --config custom-rules.yaml
        warden rules list --show-disabled
    """
    asyncio.run(list_rules(config, show_disabled))


async def list_rules(config: str, show_disabled: bool):
    """Async logic for listing rules."""
    config_path = Path(config)

    # Check if file exists
    if not config_path.exists():
        console.print(f"[red]Error:[/red] Config file not found: {config}")
        console.print(f"[dim]Hint:[/dim] Create a rules config at .warden/rules.yaml")
        raise typer.Exit(code=1)

    # Load rules
    try:
        rules_config = await RulesYAMLLoader.load_from_file(config_path)
    except Exception as e:
        console.print(f"[red]Error loading rules:[/red] {e}")
        raise typer.Exit(code=1)

    # Filter rules based on show_disabled
    rules = rules_config.rules
    if not show_disabled:
        rules = [r for r in rules if r.enabled]

    if not rules:
        console.print(f"[yellow]No rules found in {config}[/yellow]")
        raise typer.Exit(code=0)

    # Create rules table
    table = Table(
        title=f"Custom Rules ({len(rules)} total)",
        box=box.ROUNDED,
        show_header=True
    )
    table.add_column("Rule ID", style="cyan", width=25)
    table.add_column("Type", width=12)
    table.add_column("Severity", width=10)
    table.add_column("Blocker", width=8, justify="center")
    table.add_column("Enabled", width=8, justify="center")
    table.add_column("Category", width=12)

    for rule in rules:
        # Severity color
        severity_color = {
            "critical": "red bold",
            "high": "yellow",
            "medium": "blue",
            "low": "dim"
        }.get(rule.severity.value, "white")

        # Blocker indicator
        blocker = "[red]⚠ YES[/red]" if rule.is_blocker else "[dim]no[/dim]"

        # Enabled indicator
        enabled = "[green]✓[/green]" if rule.enabled else "[dim]✗[/dim]"

        table.add_row(
            rule.id,
            rule.type,
            f"[{severity_color}]{rule.severity.value.upper()}[/{severity_color}]",
            blocker,
            enabled,
            rule.category.value
        )

    console.print("\n")
    console.print(table)

    # Summary
    enabled_count = sum(1 for r in rules if r.enabled)
    blocker_count = sum(1 for r in rules if r.is_blocker)
    console.print(f"\n[dim]Enabled: {enabled_count} | Blockers: {blocker_count}[/dim]")


@app.command()
def test(
    rule_id: str = typer.Argument(..., help="Rule ID to test"),
    file_path: str = typer.Argument(..., help="File path to test against"),
    config: str = typer.Option(
        ".warden/rules.yaml",
        "--config",
        "-c",
        help="Rules config file"
    ),
):
    """
    Test a specific rule against a file.

    Runs a single rule against the specified file and reports violations.

    Example:
        warden rules test env-var-api-keys src/config.py
        warden rules test async-method-naming src/warden/pipeline/orchestrator.py
    """
    asyncio.run(test_rule(rule_id, file_path, config))


async def test_rule(rule_id: str, file_path: str, config: str):
    """Async logic for testing a single rule."""
    config_path = Path(config)
    target_file = Path(file_path)

    # Check if config exists
    if not config_path.exists():
        console.print(f"[red]Error:[/red] Config file not found: {config}")
        raise typer.Exit(code=1)

    # Check if target file exists
    if not target_file.exists():
        console.print(f"[red]Error:[/red] File not found: {file_path}")
        raise typer.Exit(code=1)

    # Load rules
    try:
        rules_config = await RulesYAMLLoader.load_from_file(config_path)
    except Exception as e:
        console.print(f"[red]Error loading rules:[/red] {e}")
        raise typer.Exit(code=1)

    # Find the rule
    rule = next((r for r in rules_config.rules if r.id == rule_id), None)
    if not rule:
        console.print(f"[red]Error:[/red] Rule not found: {rule_id}")
        console.print(f"\n[dim]Available rules:[/dim]")
        for r in rules_config.rules[:10]:
            console.print(f"  - {r.id}")
        if len(rules_config.rules) > 10:
            console.print(f"  [dim]... and {len(rules_config.rules) - 10} more[/dim]")
        raise typer.Exit(code=1)

    # Display test header
    console.print(Panel.fit(
        f"[bold cyan]Testing Rule[/bold cyan]\n"
        f"[dim]Rule:[/dim] {rule.name} ({rule.id})\n"
        f"[dim]File:[/dim] {target_file}\n"
        f"[dim]Severity:[/dim] {rule.severity.value.upper()}",
        title="Rule Test",
        border_style="cyan"
    ))

    # Create validator with single rule
    validator = CustomRuleValidator([rule])

    # Run validation
    try:
        violations = await validator.validate_file(target_file)
    except Exception as e:
        console.print(f"\n[red]Validation Error:[/red] {e}")
        raise typer.Exit(code=1)

    # Display results
    console.print("\n")
    if not violations:
        console.print(Panel(
            "[green bold]✓ No violations found![/green bold]\n"
            f"[dim]The file passes rule: {rule.name}[/dim]",
            border_style="green"
        ))
        raise typer.Exit(code=0)
    else:
        # Create violations table
        table = Table(title=f"Violations ({len(violations)})", box=box.ROUNDED)
        table.add_column("Line", width=6, justify="right")
        table.add_column("Severity", width=10)
        table.add_column("Message", style="white")

        for v in violations:
            severity_color = {
                "critical": "red bold",
                "high": "yellow",
                "medium": "blue",
                "low": "dim"
            }.get(v.severity.value, "white")

            table.add_row(
                str(v.line),
                f"[{severity_color}]{v.severity.value.upper()}[/{severity_color}]",
                v.message
            )

        console.print(table)

        # Show code snippets for first 3 violations
        if violations:
            console.print("\n[cyan]Code Snippets:[/cyan]")
            for i, v in enumerate(violations[:3], 1):
                if v.code_snippet:
                    console.print(f"\n[dim]Line {v.line}:[/dim]")
                    console.print(f"  {v.code_snippet}")
                    if v.suggestion:
                        console.print(f"  [blue]→ {v.suggestion}[/blue]")

            if len(violations) > 3:
                console.print(f"\n[dim]... and {len(violations) - 3} more violations[/dim]")

        console.print("\n")
        console.print(Panel(
            f"[red bold]✗ {len(violations)} violation(s) found[/red bold]",
            border_style="red"
        ))
        raise typer.Exit(code=1)


@app.command()
def show(
    rule_id: str = typer.Argument(..., help="Rule ID to display"),
    config: str = typer.Option(
        ".warden/rules.yaml",
        "--config",
        "-c",
        help="Rules config file"
    ),
):
    """
    Show details of a specific rule.

    Displays complete rule configuration including conditions and examples.

    Example:
        warden rules show env-var-api-keys
        warden rules show async-method-naming
    """
    asyncio.run(show_rule(rule_id, config))


async def show_rule(rule_id: str, config: str):
    """Async logic for showing rule details."""
    config_path = Path(config)

    # Check if config exists
    if not config_path.exists():
        console.print(f"[red]Error:[/red] Config file not found: {config}")
        raise typer.Exit(code=1)

    # Load rules
    try:
        rules_config = await RulesYAMLLoader.load_from_file(config_path)
    except Exception as e:
        console.print(f"[red]Error loading rules:[/red] {e}")
        raise typer.Exit(code=1)

    # Find the rule
    rule = next((r for r in rules_config.rules if r.id == rule_id), None)
    if not rule:
        console.print(f"[red]Error:[/red] Rule not found: {rule_id}")
        console.print(f"\n[dim]Available rules:[/dim]")
        for r in rules_config.rules[:10]:
            console.print(f"  - {r.id}")
        if len(rules_config.rules) > 10:
            console.print(f"  [dim]... and {len(rules_config.rules) - 10} more[/dim]")
        raise typer.Exit(code=1)

    # Display rule details in a panel
    severity_color = {
        "critical": "red bold",
        "high": "yellow",
        "medium": "blue",
        "low": "dim"
    }.get(rule.severity.value, "white")

    blocker_text = "[red bold]YES[/red bold]" if rule.is_blocker else "no"
    enabled_text = "[green]✓ Enabled[/green]" if rule.enabled else "[dim]✗ Disabled[/dim]"

    console.print(Panel.fit(
        f"[bold cyan]{rule.name}[/bold cyan]\n"
        f"[dim]ID:[/dim] {rule.id}\n"
        f"[dim]Type:[/dim] {rule.type}\n"
        f"[dim]Category:[/dim] {rule.category.value}\n"
        f"[dim]Severity:[/dim] [{severity_color}]{rule.severity.value.upper()}[/{severity_color}]\n"
        f"[dim]Blocker:[/dim] {blocker_text}\n"
        f"[dim]Status:[/dim] {enabled_text}",
        title="Rule Details",
        border_style="cyan"
    ))

    # Description
    console.print(f"\n[bold]Description:[/bold]")
    console.print(f"{rule.description}")

    # Message
    if rule.message:
        console.print(f"\n[bold]Message:[/bold]")
        console.print(f"{rule.message}")

    # Language filter
    if rule.language:
        console.print(f"\n[bold]Languages:[/bold] {', '.join(rule.language)}")

    # Conditions
    console.print(f"\n[bold]Conditions:[/bold]")
    conditions_yaml = yaml.dump(rule.conditions, default_flow_style=False, sort_keys=False)
    syntax = Syntax(conditions_yaml, "yaml", theme="monokai", line_numbers=False)
    console.print(syntax)

    # Examples
    if rule.examples:
        console.print(f"\n[bold]Examples:[/bold]")

        if "invalid" in rule.examples:
            console.print(f"\n[red]✗ Invalid:[/red]")
            for example in rule.examples["invalid"][:3]:
                console.print(f"  {example}")

        if "valid" in rule.examples:
            console.print(f"\n[green]✓ Valid:[/green]")
            for example in rule.examples["valid"][:3]:
                console.print(f"  {example}")

    # Exceptions
    if rule.exceptions:
        console.print(f"\n[bold]Exceptions (excluded files):[/bold]")
        for pattern in rule.exceptions[:5]:
            console.print(f"  - {pattern}")
        if len(rule.exceptions) > 5:
            console.print(f"  [dim]... and {len(rule.exceptions) - 5} more patterns[/dim]")


if __name__ == "__main__":
    app()
