"""
TUI Rules Command - Display and manage custom validation rules

Shows configured rules, their status, and allows filtering/testing.
"""

import asyncio
from pathlib import Path
from rich.table import Table
from rich.panel import Panel
from rich.syntax import Syntax
from rich import box

from warden.rules.infrastructure.yaml_loader import RulesYAMLLoader


async def execute(app, args: str = ""):
    """
    Execute /rules command in TUI.

    Args:
        app: TUI app instance
        args: Optional arguments (list, show <rule-id>, test <rule-id>)
    """
    try:
        # Load rules
        rules_file = app.project_root / ".warden" / "rules.yaml"

        if not rules_file.exists():
            app._add_message(
                "❌ No rules.yaml found. Create one at .warden/rules.yaml",
                "error-message"
            )
            return

        # Parse command arguments
        parts = args.strip().split()
        command = parts[0] if parts else "list"

        if command == "list":
            await _list_rules(app, rules_file)
        elif command == "show" and len(parts) > 1:
            await _show_rule(app, rules_file, parts[1])
        elif command == "stats":
            await _show_stats(app, rules_file)
        else:
            await _show_help(app)

    except Exception as e:
        app._add_message(
            f"❌ Error loading rules: {str(e)}",
            "error-message"
        )


async def _list_rules(app, rules_file: Path):
    """Display all configured rules in a table."""
    config = await RulesYAMLLoader.load_from_file(rules_file)

    # Create rules table
    table = Table(
        title=f"Custom Rules ({len(config.rules)} total)",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan"
    )

    table.add_column("Rule ID", style="cyan", width=25)
    table.add_column("Type", width=12)
    table.add_column("Severity", width=10)
    table.add_column("Blocker", width=8)
    table.add_column("Status", width=8)

    # Add rules
    for rule in config.rules:
        severity_color = {
            "critical": "red bold",
            "high": "yellow",
            "medium": "blue",
            "low": "dim"
        }.get(rule.severity.value, "white")

        blocker = "⚠ YES" if rule.is_blocker else "no"
        status = "✓" if rule.enabled else "✗"
        status_color = "green" if rule.enabled else "dim"

        table.add_row(
            rule.id,
            rule.type,
            f"[{severity_color}]{rule.severity.value.upper()}[/{severity_color}]",
            f"[red]{blocker}[/red]" if rule.is_blocker else blocker,
            f"[{status_color}]{status}[/{status_color}]"
        )

    # Show global rules
    global_info = ""
    if config.global_rules:
        global_info = f"\n\n**Global Rules ({len(config.global_rules)}):** {', '.join(config.global_rules)}"

    # Show frame rules
    frame_info = ""
    if config.frame_rules:
        frame_info = f"\n**Frame Rules:** {len(config.frame_rules)} frames configured"

    app._add_message(table, "message")

    if global_info or frame_info:
        app._add_message(
            Panel(
                global_info + frame_info,
                title="Rules Configuration",
                border_style="cyan"
            ),
            "message"
        )


async def _show_rule(app, rules_file: Path, rule_id: str):
    """Display detailed information about a specific rule."""
    config = await RulesYAMLLoader.load_from_file(rules_file)

    # Find rule
    rule = next((r for r in config.rules if r.id == rule_id), None)

    if not rule:
        app._add_message(
            f"❌ Rule '{rule_id}' not found",
            "error-message"
        )
        return

    # Create detail panel
    details = f"""**{rule.name}**

**ID:** {rule.id}
**Type:** {rule.type}
**Category:** {rule.category.value}
**Severity:** {rule.severity.value.upper()}
**Blocker:** {'YES ⚠' if rule.is_blocker else 'NO'}
**Status:** {'✓ Enabled' if rule.enabled else '✗ Disabled'}

**Description:**
{rule.description}
"""

    if rule.message:
        details += f"\n**Message:**\n{rule.message}"

    app._add_message(
        Panel(details, title=f"Rule: {rule_id}", border_style="cyan"),
        "message",
        markdown=True
    )

    # Show conditions (YAML)
    if rule.conditions:
        import yaml
        conditions_yaml = yaml.dump(rule.conditions, default_flow_style=False)
        syntax = Syntax(conditions_yaml, "yaml", theme="monokai", line_numbers=False)

        app._add_message(
            Panel(syntax, title="Conditions", border_style="blue"),
            "message"
        )

    # Show examples
    if rule.examples:
        examples_text = ""
        if rule.examples.get("invalid"):
            examples_text += "**❌ Invalid Examples:**\n"
            for ex in rule.examples["invalid"][:3]:
                examples_text += f"  - {ex}\n"

        if rule.examples.get("valid"):
            examples_text += "\n**✓ Valid Examples:**\n"
            for ex in rule.examples["valid"][:3]:
                examples_text += f"  - {ex}\n"

        if examples_text:
            app._add_message(
                Panel(examples_text, title="Examples", border_style="green"),
                "message",
                markdown=True
            )


async def _show_stats(app, rules_file: Path):
    """Show rules statistics."""
    config = await RulesYAMLLoader.load_from_file(rules_file)

    # Calculate stats
    total_rules = len(config.rules)
    enabled_rules = sum(1 for r in config.rules if r.enabled)
    blocker_rules = sum(1 for r in config.rules if r.is_blocker)

    severity_counts = {}
    type_counts = {}

    for rule in config.rules:
        severity_counts[rule.severity.value] = severity_counts.get(rule.severity.value, 0) + 1
        type_counts[rule.type] = type_counts.get(rule.type, 0) + 1

    stats = f"""**Rules Statistics**

**Total Rules:** {total_rules}
**Enabled:** {enabled_rules}
**Disabled:** {total_rules - enabled_rules}
**Blockers:** {blocker_rules}

**By Severity:**
"""

    for severity, count in sorted(severity_counts.items()):
        stats += f"  - {severity.upper()}: {count}\n"

    stats += "\n**By Type:**\n"
    for rule_type, count in sorted(type_counts.items()):
        stats += f"  - {rule_type}: {count}\n"

    stats += f"\n**Global Rules:** {len(config.global_rules)}"
    stats += f"\n**Frame Rules:** {len(config.frame_rules)} frames"

    app._add_message(
        Panel(stats, title="📊 Rules Statistics", border_style="cyan"),
        "message",
        markdown=True
    )


async def _show_help(app):
    """Show rules command help."""
    help_text = """**📜 /rules - Custom Rules Management**

**Available Commands:**

`/rules` or `/rules list`
  Show all configured rules in a table

`/rules show <rule-id>`
  Display detailed information about a specific rule

`/rules stats`
  Show rules statistics and distribution

**Examples:**
  `/rules`
  `/rules show no-secrets`
  `/rules show async-method-naming`
  `/rules stats`

**Quick Actions:**
  - View rule details before running validation
  - Check which rules are enabled/disabled
  - See blocker rules that halt execution
  - Review rule conditions and examples
"""

    app._add_message(
        Panel(help_text, title="Rules Command Help", border_style="cyan"),
        "message",
        markdown=True
    )
