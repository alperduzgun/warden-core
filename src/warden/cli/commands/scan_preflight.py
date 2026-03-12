from pathlib import Path

from rich.console import Console

console = Console()


def _needs_ollama() -> bool:
    """Return True if the project config requires Ollama."""
    import os

    import yaml

    # Respect CI env var overrides — if provider is forced to a cloud provider, skip
    env_provider = os.environ.get("WARDEN_LLM_PROVIDER", "").strip().lower()
    if env_provider and env_provider != "ollama":
        return False

    config_candidates = [Path.cwd() / "warden.yaml", Path.cwd() / ".warden" / "config.yaml"]
    for cfg_path in config_candidates:
        if cfg_path.exists():
            try:
                with open(cfg_path) as f:
                    data = yaml.safe_load(f) or {}
                llm = data.get("llm", {})
                provider = llm.get("provider", "")
                use_local = llm.get("use_local_llm", False)
                return provider == "ollama" or bool(use_local)
            except Exception:
                return False

    return False


def _preflight_ollama_check(rich_console: "Console") -> bool:
    """
    Verify Ollama is running and required models are present before scan starts.

    Returns True when ready (or Ollama is not needed).
    Returns False when a blocking issue could not be resolved.
    """
    if not _needs_ollama():
        return True

    from warden.services.local_model_manager import LocalModelManager

    manager = LocalModelManager()

    # 1. Check binary exists first — distinct message from "server not running"
    rich_console.print("[dim]🔍 Preflight: checking Ollama...[/dim]")
    if not manager.is_installed():
        rich_console.print("[red]❌ Ollama is not installed.[/red]")
        rich_console.print("[dim]   macOS : brew install ollama[/dim]")
        rich_console.print("[dim]   Linux : curl -fsSL https://ollama.com/install.sh | sh[/dim]")
        rich_console.print("[dim]   or    : https://ollama.com/download[/dim]")
        rich_console.print("[dim]   After installing, run: warden scan (preflight will auto-start the server)[/dim]")
        return False

    # 2. Ensure server is running
    if not manager.ensure_ollama_running():
        rich_console.print("[red]❌ Ollama could not be started.[/red]")
        rich_console.print("[dim]   Try running: ollama serve[/dim]")
        return False

    # 2. Check required models
    missing = [m for m in manager.get_configured_models() if not manager.is_model_available(m)]
    if not missing:
        return True

    # 3. Pull missing models (always auto-pull in scan context — user already chose Ollama)
    for model in missing:
        rich_console.print(f"[yellow]⚠️  Model missing: {model} — pulling now...[/yellow]")
        success = manager.pull_model(model, show_progress=True)
        if not success:
            rich_console.print(f"[red]❌ Failed to pull model '{model}'. Run: ollama pull {model}[/red]")
            return False

    return True


def _ensure_scan_dependencies(level: str) -> None:
    """Auto-install missing packages needed for the given scan level."""
    try:
        from warden.services.dependencies.auto_resolver import ensure_dependencies

        needed: list[str] = []
        if level in ("standard", "deep"):
            needed.append("tiktoken")

        if not needed:
            return

        still_missing = ensure_dependencies(needed, context=f"scan --level {level}")
        if still_missing:
            console.print(
                f"[yellow]Optional dependencies unavailable: {', '.join(still_missing)}. "
                f"Scan will use fallback heuristics.[/yellow]"
            )
    except Exception:
        pass  # Dependency check is best-effort, never block the scan
