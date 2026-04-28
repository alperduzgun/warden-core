"""
Warden hooks CLI — manage Git hooks installation.
"""

from pathlib import Path

import typer

from rich.console import Console

console = Console()

hooks_app = typer.Typer(
    name="hooks",
    help="Manage Warden git hooks (pre-commit, pre-push, commit-msg).",
    no_args_is_help=True,
)


@hooks_app.command("install")
def install(
    hook_names: list[str] = typer.Argument(None, help="Hook names to install (default: all)"),
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing hooks"),
) -> None:
    """Install Warden git hooks."""
    from warden.infrastructure.hooks.installer import HookInstaller

    results = HookInstaller.install_hooks(
        hooks=hook_names or None,
        force=force,
    )
    for r in results:
        status = "[green]✓[/green]" if r.installed else "[yellow]⚠[/yellow]"
        console.print(f"  {status} {r.hook_name}: {r.message}")


@hooks_app.command("uninstall")
def uninstall(
    hook_names: list[str] = typer.Argument(None, help="Hook names to uninstall (default: all)"),
) -> None:
    """Uninstall Warden git hooks."""
    from warden.infrastructure.hooks.installer import HookInstaller

    results = HookInstaller.uninstall_hooks(hooks=hook_names or None)
    for r in results:
        status = "[green]✓[/green]" if r.installed is False else "[yellow]⚠[/yellow]"
        console.print(f"  {status} {r.hook_name}: {r.message}")


@hooks_app.command("status")
def status() -> None:
    """Show installed Warden hooks."""
    from warden.infrastructure.hooks.installer import HookInstaller

    installed = HookInstaller.list_hooks()
    for name, is_installed in installed.items():
        icon = "[green]✓[/green]" if is_installed else "[red]✗[/red]"
        console.print(f"  {icon} {name}")
