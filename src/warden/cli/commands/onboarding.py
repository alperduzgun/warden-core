"""
First-time onboarding flow shown after initial sign-up via ``warden login``.
"""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from warden.auth.client import AuthClient
from warden.auth.models import AuthSession
from warden.shared.infrastructure.logging import get_logger

console = Console()
logger = get_logger(__name__)

_ROLES = [
    "developer",
    "tech-lead",
    "devops",
    "security-engineer",
    "architect",
    "other",
]


async def run_onboarding(client: AuthClient, session: AuthSession) -> None:
    """Interactive onboarding for first-time users."""
    console.print()
    welcome = Panel(
        "\n  [bold]Welcome to Warden Cloud![/bold]\n"
        "  Let's set up your account in a few quick steps.\n",
        border_style="green",
        expand=False,
    )
    console.print(welcome)

    # 1. Role selection
    console.print("[bold]What best describes your role?[/bold]")
    for i, role in enumerate(_ROLES, 1):
        console.print(f"  [cyan]{i}[/cyan]. {role}")

    choice = Prompt.ask(
        "Select a number",
        choices=[str(i) for i in range(1, len(_ROLES) + 1)],
        default="1",
    )
    selected_role = _ROLES[int(choice) - 1]

    # 2. Workspace name (optional)
    workspace_name = Prompt.ask(
        "Workspace name (team or org)",
        default="",
    )

    # 3. Submit to backend
    try:
        with console.status("[bold cyan]Saving...", spinner="dots"):
            await client.complete_onboarding(
                session.tokens.access_token,
                role=selected_role,
                workspace_name=workspace_name or None,
            )
        console.print("[green]Onboarding complete![/green]")
    except Exception as exc:
        logger.warning("onboarding_submit_failed", error=str(exc))
        console.print("[yellow]Could not save onboarding data. You can update later from the dashboard.[/yellow]")
