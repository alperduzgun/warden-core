"""
Interactive LLM provider selection — same Rich+Prompt pattern as warden init.
Called by: warden config llm edit
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table

from .init_helpers import LLM_PROVIDERS

console = Console()

# Providers blocked in CI — CLI tools that require a local binary.
# Ollama IS supported in CI (can be installed via install.sh + ollama serve).
# Source of truth: init_helpers.LLM_PROVIDERS[x]["ci_supported"]
_CI_BLOCKED = {p["id"] for p in LLM_PROVIDERS.values() if not p.get("ci_supported", True)}

# (id, label) for fast tier; "none" disables it
_FAST_NONE = {
    "id": "none",
    "name": "None (disabled)",
    "emoji": "—",
    "description": "Fast tier disabled",
    "default_model": "",
}


@dataclass
class LlmConfigResult:
    saved: bool = False
    local_smart_provider: str = "ollama"
    local_smart_model: str = ""
    local_fast_provider: str = "ollama"
    local_fast_model: str = ""
    ci_smart_provider: str = "groq"
    ci_smart_model: str = ""
    ci_fast_provider: str = "groq"
    ci_fast_model: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _provider_table(providers: dict, current_id: str) -> None:
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Key", style="bold cyan", width=4)
    table.add_column("Provider", style="bold white", width=28)
    table.add_column("Model", style="dim", width=30)
    table.add_column("", style="dim")
    for key, p in providers.items():
        current = " [green]← current[/green]" if p["id"] == current_id else ""
        table.add_row(
            f"[{key}]",
            f"{p['emoji']} {p['name']}{current}",
            p.get("default_model", ""),
            p.get("description", ""),
        )
    console.print(table)


def _pick_provider(providers: dict, prompt_text: str, current_id: str) -> dict:
    """Show table, prompt for choice, return provider dict."""
    _provider_table(providers, current_id)
    console.print()
    default_key = next(
        (k for k, p in providers.items() if p["id"] == current_id),
        next(iter(providers)),
    )
    choice = Prompt.ask(prompt_text, choices=list(providers.keys()), default=default_key)
    return providers[choice]


def _pick_model(provider: dict, current_model: str) -> str:
    default = current_model or provider.get("default_model", "")
    model = Prompt.ask("  Model", default=default)
    return model.strip()


def _configure_tier(
    tier_name: str,
    providers: dict,
    current_provider_id: str,
    current_model: str,
) -> tuple[str, str]:
    """Select provider + model for one tier. Returns (provider_id, model)."""
    console.print(f"\n[bold cyan]{tier_name}[/bold cyan]")
    p = _pick_provider(providers, "  Provider", current_provider_id)
    if p["id"] == "none":
        return "none", ""
    model = _pick_model(p, current_model)
    return p["id"], model


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_llm_config_ui(current: dict) -> LlmConfigResult | None:
    """
    Interactive Rich+Prompt flow identical to warden init style.
    Returns LlmConfigResult or None if user cancels.
    """
    result = LlmConfigResult()

    # ── What to configure ───────────────────────────────────────────────────
    console.print("\n[bold]Configure LLM providers[/bold]")
    console.print("[dim]Local — used when running warden on your machine[/dim]")
    console.print("[dim]CI    — used in GitHub Actions / GitLab CI pipelines[/dim]\n")

    scope_table = Table(show_header=False, box=None, padding=(0, 2))
    scope_table.add_column("Key", style="bold cyan", width=4)
    scope_table.add_column("Scope", style="bold white")
    scope_table.add_row("[1]", "Local only")
    scope_table.add_row("[2]", "CI / CD only")
    scope_table.add_row("[3]", "Both")
    console.print(scope_table)
    console.print()

    scope = Prompt.ask("Configure", choices=["1", "2", "3"], default="3")

    # ── Build provider lists ────────────────────────────────────────────────
    local_providers = dict(LLM_PROVIDERS)  # all providers
    ci_providers = {k: v for k, v in LLM_PROVIDERS.items() if v["id"] not in _CI_BLOCKED}

    # Add "none" as last option for fast tier
    last_local = str(max(int(k) for k in local_providers) + 1)
    last_ci = str(max(int(k) for k in ci_providers) + 1)
    fast_local = dict(local_providers) | {last_local: _FAST_NONE}
    fast_ci = dict(ci_providers) | {last_ci: _FAST_NONE}

    # ── Local ────────────────────────────────────────────────────────────────
    if scope in ("1", "3"):
        console.rule("[bold]Local Configuration[/bold]")

        s_prov, s_model = _configure_tier(
            "Smart tier  (security · analysis)",
            local_providers,
            current.get("local_smart_provider", "ollama"),
            current.get("local_smart_model", ""),
        )
        f_prov, f_model = _configure_tier(
            "Fast tier   (triage · classification)",
            fast_local,
            current.get("local_fast_provider", "ollama"),
            current.get("local_fast_model", ""),
        )
        result.local_smart_provider = s_prov
        result.local_smart_model = s_model
        result.local_fast_provider = f_prov
        result.local_fast_model = f_model
    else:
        result.local_smart_provider = current.get("local_smart_provider", "ollama")
        result.local_smart_model = current.get("local_smart_model", "")
        result.local_fast_provider = current.get("local_fast_provider", "ollama")
        result.local_fast_model = current.get("local_fast_model", "")

    # ── CI ───────────────────────────────────────────────────────────────────
    if scope in ("2", "3"):
        console.rule("[bold]CI / CD Configuration[/bold]")
        console.print("[dim]CLI tools and local servers (Ollama, Claude Code, Codex, QwenCode) are excluded.[/dim]")

        s_prov, s_model = _configure_tier(
            "Smart tier  (security · analysis)",
            ci_providers,
            current.get("ci_smart_provider", "groq"),
            current.get("ci_smart_model", ""),
        )
        f_prov, f_model = _configure_tier(
            "Fast tier   (triage · classification)",
            fast_ci,
            current.get("ci_fast_provider", "groq"),
            current.get("ci_fast_model", ""),
        )
        result.ci_smart_provider = s_prov
        result.ci_smart_model = s_model
        result.ci_fast_provider = f_prov
        result.ci_fast_model = f_model
    else:
        result.ci_smart_provider = current.get("ci_smart_provider", "groq")
        result.ci_smart_model = current.get("ci_smart_model", "")
        result.ci_fast_provider = current.get("ci_fast_provider", "groq")
        result.ci_fast_model = current.get("ci_fast_model", "")

    result.saved = True
    return result
