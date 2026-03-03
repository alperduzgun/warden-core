"""
CLI auth commands: ``warden login``, ``warden logout``, ``warden whoami``.
"""

from __future__ import annotations

import asyncio
import webbrowser

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from warden.auth.client import AuthClient
from warden.auth.credentials import CredentialStore
from warden.shared.infrastructure.logging import get_logger

console = Console()
logger = get_logger(__name__)


# ------------------------------------------------------------------
# Shared helpers
# ------------------------------------------------------------------

def _get_store() -> CredentialStore:
    return CredentialStore()


def _get_client() -> AuthClient:
    return AuthClient()


async def _run_login(force: bool = False) -> bool:
    """Core login flow reused by ``login_command`` and ``init`` integration.

    Returns ``True`` on success.
    """
    store = _get_store()
    client = _get_client()

    # Already logged in?
    session = store.load()
    if session and not store.is_expired(session) and not force:
        console.print(
            f"[green]Already logged in as [bold]{session.user.email}[/bold].[/green] "
            "Use [cyan]--force[/cyan] to re-login."
        )
        return True

    # 1. Init CLI session
    try:
        with console.status("[bold cyan]Contacting Warden Cloud...", spinner="dots"):
            auth_resp = await client.init_cli_session()
    except Exception as exc:
        logger.error("cli_session_init_failed", error=str(exc))
        console.print(f"[bold red]Failed to reach Warden Cloud:[/bold red] {exc}")
        raise typer.Exit(1)

    # 2. Show login URL
    url_panel = Panel(
        f"\n  Open this URL to authenticate:\n  [bold cyan]{auth_resp.login_url}[/bold cyan]\n",
        title="Warden Cloud Login",
        border_style="blue",
        expand=False,
    )
    console.print(url_panel)

    # 3. Auto-open browser
    try:
        webbrowser.open(auth_resp.login_url)
        console.print("[dim]Browser opened automatically.[/dim]")
    except Exception:
        console.print("[dim]Could not open browser. Please open the URL manually.[/dim]")

    # 4. Wait for user
    Prompt.ask("\n[bold]Press Enter after logging in the browser[/bold]")

    # 5. Poll session
    max_retries = 3
    session = None
    for attempt in range(1, max_retries + 1):
        try:
            with console.status("[bold cyan]Verifying authentication...", spinner="dots"):
                session = await client.poll_cli_session(auth_resp.session_id)
        except Exception as exc:
            logger.error("poll_failed", error=str(exc), attempt=attempt)

        if session:
            break

        if attempt < max_retries:
            if Confirm.ask("[yellow]Authentication not completed. Try again?[/yellow]"):
                Prompt.ask("[bold]Press Enter after logging in the browser[/bold]")
            else:
                console.print("[red]Login cancelled.[/red]")
                return False
        else:
            console.print("[bold red]Authentication failed after multiple attempts.[/bold red]")
            return False

    # 6. Save credentials
    store.save(session)

    # 7. Onboarding check
    if not session.user.is_onboarded:
        from warden.cli.commands.onboarding import run_onboarding

        await run_onboarding(client, session)

    # 8. Success
    display_name = session.user.name or session.user.email
    console.print(f"\n[bold green]Logged in as {display_name} ({session.user.email})[/bold green]")
    return True


# ------------------------------------------------------------------
# Commands
# ------------------------------------------------------------------

def login_command(
    ctx: typer.Context,
    force: bool = typer.Option(False, "--force", "-f", help="Re-login even if already authenticated"),
) -> None:
    """Authenticate with Warden Cloud via browser."""
    asyncio.run(_run_login(force=force))


def logout_command(ctx: typer.Context) -> None:
    """Log out of Warden Cloud and remove local credentials."""
    store = _get_store()
    session = store.load()

    if session is None:
        console.print("[dim]Not currently logged in.[/dim]")
        raise typer.Exit(0)

    # Invalidate remote session (best-effort)
    try:
        client = _get_client()
        asyncio.run(client.logout(session.tokens.access_token))
    except Exception as exc:
        logger.warning("remote_logout_error", error=str(exc))

    store.clear()
    console.print("[green]Logged out successfully.[/green]")


def whoami_command(ctx: typer.Context) -> None:
    """Show the currently authenticated user."""
    store = _get_store()
    session = store.load()

    if session is None:
        console.print("[dim]Not logged in. Run [cyan]warden /login[/cyan] to authenticate.[/dim]")
        raise typer.Exit(0)

    expired = store.is_expired(session)

    table = Table(show_header=False, expand=False, border_style="cyan")
    table.add_column("Field", style="bold")
    table.add_column("Value")

    table.add_row("Name", session.user.name or "-")
    table.add_row("Email", session.user.email)
    table.add_row("Role", session.user.role or "-")

    if session.workspaces:
        ws = session.workspaces[0]
        table.add_row("Workspace", ws.name)
        if ws.plan:
            table.add_row("Plan", ws.plan)

    status = "[red]Expired[/red]" if expired else "[green]Active[/green]"
    table.add_row("Session", status)

    panel = Panel(table, title="Warden Cloud Account", border_style="blue", expand=False)
    console.print(panel)
