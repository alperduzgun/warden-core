from pathlib import Path

from rich.console import Console

console = Console()


_CLOUD_PROVIDERS = frozenset({
    "anthropic", "openai", "groq", "azure", "deepseek", "gemini",
    "azure_openai", "qwencode",
})

# Mapping from provider name to the environment variable that supplies its API key.
_CLOUD_PROVIDER_KEY_ENV: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "groq": "GROQ_API_KEY",
    "azure": "AZURE_OPENAI_API_KEY",
    "azure_openai": "AZURE_OPENAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "qwencode": "QWENCODE_API_KEY",
}


def _needs_ollama() -> bool:
    """Return True only if the project config explicitly requires Ollama
    AND no cloud provider override is active (env or config routing)."""
    import os

    import yaml

    # 1. Env var override — highest priority
    env_provider = os.environ.get("WARDEN_LLM_PROVIDER", "").strip().lower()
    if env_provider:
        return env_provider == "ollama"

    config_candidates = [Path.cwd() / "warden.yaml", Path.cwd() / ".warden" / "config.yaml"]
    for cfg_path in config_candidates:
        if cfg_path.exists():
            try:
                with open(cfg_path) as f:
                    data = yaml.safe_load(f) or {}
                llm = data.get("llm", {}) or {}
                provider = (llm.get("provider", "") or "").lower()

                # 2. Explicit local LLM flag always requires Ollama
                use_local = llm.get("use_local_llm", False)
                if use_local:
                    return True

                # 3. If primary provider is a cloud service, no Ollama needed
                if provider in _CLOUD_PROVIDERS:
                    return False

                # 4. Check routing — if smart_tier is cloud, Ollama is optional
                routing = data.get("routing", {}) or {}
                smart_tier = (routing.get("smart_tier", "") or "").lower()
                if smart_tier in _CLOUD_PROVIDERS:
                    return False

                return provider == "ollama"
            except Exception:
                return False

    return False


def _preflight_cloud_provider_check(rich_console: "Console") -> bool:
    """
    Verify that the configured cloud provider has a non-empty API key set.

    Returns True when the key is present (or the provider is local / not cloud).
    Returns False and prints an actionable error when the key is absent.
    """
    import os

    import yaml

    config_candidates = [Path.cwd() / "warden.yaml", Path.cwd() / ".warden" / "config.yaml"]
    provider: str = ""
    for cfg_path in config_candidates:
        if cfg_path.exists():
            try:
                with open(cfg_path) as f:
                    data = yaml.safe_load(f) or {}
                llm = data.get("llm", {}) or {}
                provider = (llm.get("provider") or llm.get("default_provider") or "").strip().lower()
            except Exception:
                return True  # Cannot read config — let the bridge raise later
            break

    # Also respect env var override (highest priority).
    env_provider = os.environ.get("WARDEN_LLM_PROVIDER", "").strip().lower()
    if env_provider and env_provider != "auto":
        provider = env_provider

    if not provider or provider == "auto" or provider not in _CLOUD_PROVIDERS:
        return True  # Local provider or auto-detect — no key required here

    env_var = _CLOUD_PROVIDER_KEY_ENV.get(provider)
    if not env_var:
        return True  # Unknown cloud provider — let it pass; bridge will validate

    api_key = os.environ.get(env_var, "").strip()
    if not api_key:
        rich_console.print(
            f"[red]❌ Preflight failed: cloud provider '[bold]{provider}[/bold]' "
            f"requires [bold]{env_var}[/bold] but it is not set.[/red]"
        )
        rich_console.print(
            f"[dim]   Set it with: export {env_var}=<your-api-key>[/dim]"
        )
        rich_console.print(
            "[dim]   Or switch to a local provider: warden config llm[/dim]"
        )
        return False

    return True


def _preflight_ollama_check(rich_console: "Console") -> bool:
    """
    Verify Ollama is running and required models are present before scan starts.

    Returns True when ready (or Ollama is not needed).
    Returns False when a blocking issue could not be resolved.
    """
    # Cloud provider API key check runs first — fast and no I/O beyond env reads.
    if not _preflight_cloud_provider_check(rich_console):
        return False

    if not _needs_ollama():
        return True

    from warden.services.local_model_manager import LocalModelManager

    manager = LocalModelManager()

    # 1. Check binary exists first — distinct message from "server not running"
    rich_console.print("[dim]🔍 Preflight: checking Ollama...[/dim]")
    if not manager.is_installed():
        rich_console.print("[yellow]⚠ Ollama is not installed. LLM features will be disabled.[/yellow]")
        rich_console.print("[dim]   Install: brew install ollama (macOS) or https://ollama.com/download[/dim]")
        rich_console.print("[dim]   Scan continues with deterministic analysis only.[/dim]")
        return True  # Continue without LLM — don't block the scan

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
