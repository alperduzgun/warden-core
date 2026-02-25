"""
Initialization Helpers for Warden CLI.
Handles interactive configuration prompts with improved UX.
"""

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.table import Table

console = Console()

# =============================================================================
# LLM Provider Configuration
# =============================================================================

LLM_PROVIDERS = {
    "1": {
        "id": "ollama",
        "name": "Ollama (Local)",
        "description": "Free, private, runs on your machine",
        "emoji": "🏠",
        "requires_key": False,
        "default_model": "qwen2.5-coder:7b",
        "ci_supported": True,
    },
    "2": {
        "id": "anthropic",
        "name": "Anthropic Claude",
        "description": "Best quality, recommended for production",
        "emoji": "🧠",
        "requires_key": True,
        "key_var": "ANTHROPIC_API_KEY",
        "key_prefix": "sk-ant-",
        "default_model": "claude-sonnet-4-20250514",
        "ci_supported": True,
    },
    "3": {
        "id": "openai",
        "name": "OpenAI",
        "description": "Popular choice, good balance",
        "emoji": "🤖",
        "requires_key": True,
        "key_var": "OPENAI_API_KEY",
        "key_prefix": "sk-",
        "default_model": "gpt-4o",
        "ci_supported": True,
    },
    "4": {
        "id": "groq",
        "name": "Groq",
        "description": "Fast & cheap, great for CI/CD",
        "emoji": "⚡",
        "requires_key": True,
        "key_var": "GROQ_API_KEY",
        "key_prefix": "gsk_",
        "default_model": "llama-3.3-70b-versatile",
        "ci_supported": True,
    },
    "5": {
        "id": "azure",
        "name": "Azure OpenAI",
        "description": "Enterprise, compliance-ready",
        "emoji": "☁️",
        "requires_key": True,
        "key_var": "AZURE_OPENAI_API_KEY",
        "default_model": "gpt-4o",
        "ci_supported": True,
    },
    "6": {
        "id": "deepseek",
        "name": "DeepSeek",
        "description": "Budget-friendly alternative",
        "emoji": "🔍",
        "requires_key": True,
        "key_var": "DEEPSEEK_API_KEY",
        "default_model": "deepseek-coder",
        "ci_supported": True,
    },
    "7": {
        "id": "gemini",
        "name": "Google Gemini",
        "description": "High performance, large context window",
        "emoji": "✨",
        "requires_key": True,
        "key_var": "GEMINI_API_KEY",
        "default_model": "gemini-1.5-flash",
        "ci_supported": True,
    },
    "8": {
        "id": "claude_code",
        "name": "Claude Code (Local)",
        "description": "Use your Claude Code subscription locally",
        "emoji": "🖥️",
        "requires_key": False,
        "default_model": "claude-sonnet-4-20250514",
        "ci_supported": False,  # Local CLI only — not available in CI runners
    },
    "9": {
        "id": "codex",
        "name": "Codex (Local)",
        "description": "Use local Codex CLI integration (file-based)",
        "emoji": "🧩",
        "requires_key": False,
        "default_model": "codex-local",
        "ci_supported": False,
    },
}


def _is_ci_environment() -> bool:
    """Detect CI/headless environment where local-only providers can't work."""
    ci_vars = ["CI", "GITHUB_ACTIONS", "GITLAB_CI", "CIRCLECI", "JENKINS_URL", "TRAVIS"]
    return (
        any(os.environ.get(v, "").lower() in ("true", "1", "yes") for v in ci_vars)
        or os.environ.get("WARDEN_NON_INTERACTIVE", "").lower() == "true"
        or not sys.stdin.isatty()
    )


CI_PROVIDERS = {
    "1": {
        "id": "github",
        "name": "GitHub Actions",
        "template": "github.yml",
        "target_path": ".github/workflows/warden.yml",
    },
    "2": {"id": "gitlab", "name": "GitLab CI", "template": "gitlab.yml", "target_path": ".gitlab-ci.yml"},
    "3": {"id": "skip", "name": "Skip (Configure Later)", "template": None, "target_path": None},
}


def select_llm_provider() -> dict:
    """
    Display LLM provider selection UI with smart default detection.
    Returns selected provider info.

    Respects:
    - ``WARDEN_INIT_PROVIDER`` env var: directly selects a provider (set by --provider flag)
    - CI environments: filters out providers with ``ci_supported=False`` (e.g. claude_code)
    """
    is_ci = _is_ci_environment()

    # Filter providers based on CI context
    available = {k: v for k, v in LLM_PROVIDERS.items() if not is_ci or v.get("ci_supported", True)}

    # --provider flag support: init.py sets WARDEN_INIT_PROVIDER before calling configure_llm()
    # Explicit --provider bypasses CI filter (user made an intentional choice)
    forced = os.environ.get("WARDEN_INIT_PROVIDER", "").strip().lower()
    if forced:
        match = next((v for v in LLM_PROVIDERS.values() if v["id"] == forced), None)
        if match:
            return match
        # Warn and fall through to interactive/auto selection
        console.print(f"[yellow]Warning: Provider '{forced}' is unknown or not supported in this context.[/yellow]")

    console.print("\n[bold cyan]🧠 Step 1: Select LLM Provider[/bold cyan]")
    if is_ci:
        console.print("[dim]CI environment detected — local-only providers (claude_code) are hidden.[/dim]\n")
    else:
        console.print("[dim]Warden requires an LLM for AI-powered analysis.[/dim]\n")

    # SMART DEFAULT: Detect available local providers
    default_choice = "1"  # Ollama
    detected_providers = {}

    if not is_ci:
        # Check Claude Code availability (only in interactive/local mode)
        claude_path = shutil.which("claude")
        if claude_path:
            try:
                result = subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=2)
                if result.returncode == 0:
                    default_choice = "8"  # Claude Code detected!
                    detected_providers["8"] = " [green](Detected ✓)[/green]"
            except (subprocess.TimeoutExpired, Exception):
                pass
        # Check Codex availability as alternative local option
        codex_path = shutil.which("codex")
        if codex_path:
            detected_providers["9"] = " [dim](Available)[/dim]"

    # Check Ollama availability
    if shutil.which("ollama"):
        detected_providers["1"] = " [dim](Available)[/dim]"

    # Build selection table with detection status (only show available providers)
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Option", style="bold cyan", width=3)
    table.add_column("Provider", style="bold white", width=30)
    table.add_column("Description", style="dim")

    for key, provider in available.items():
        detected = detected_providers.get(key, "")
        table.add_row(f"[{key}]", f"{provider['emoji']} {provider['name']}{detected}", provider["description"])

    console.print(table)
    console.print()

    is_interactive = sys.stdin.isatty() and os.environ.get("WARDEN_NON_INTERACTIVE") != "true"

    # Ensure default_choice is in available set (CI may have removed claude_code)
    if default_choice not in available:
        default_choice = next(iter(available), "1")

    choice = default_choice  # Smart default based on detection
    if is_interactive:
        choice = Prompt.ask("Select provider", choices=list(available.keys()), default=default_choice)

    return available[choice]


def configure_ollama() -> tuple[dict, dict]:
    """
    Configure Ollama (local LLM).
    Checks if Ollama is installed, offers installation if not.
    Returns (llm_config, env_vars).
    """
    console.print("\n[bold cyan]🏠 Configuring Ollama (Local LLM)[/bold cyan]")

    # Check if Ollama is installed
    ollama_path = shutil.which("ollama")

    is_interactive = sys.stdin.isatty() and os.environ.get("WARDEN_NON_INTERACTIVE") != "true"

    if not ollama_path:
        console.print("[yellow]⚠️  Ollama is not installed.[/yellow]")

        should_install = False
        if is_interactive:
            should_install = Confirm.ask("Install Ollama now?", default=True)

        if should_install:
            console.print("[dim]Installing Ollama...[/dim]")
            try:
                # Linux/macOS installation
                subprocess.run(["bash", "-c", "curl -fsSL https://ollama.com/install.sh | sh"], check=True)
                console.print("[green]✓ Ollama installed successfully![/green]")
            except subprocess.CalledProcessError:
                console.print("[red]Installation failed. Please install manually:[/red]")
                console.print("[dim]https://ollama.com/download[/dim]")
                return _fallback_to_cloud_provider()
        else:
            console.print("[yellow]Ollama is required for local LLM. Falling back to cloud provider.[/yellow]")
            return _fallback_to_cloud_provider()
    else:
        console.print(f"[green]✓ Ollama found at: {ollama_path}[/green]")

    # Check if Ollama server is running
    ollama_host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

    # Validate OLLAMA_HOST URL to prevent SSRF
    from urllib.parse import urlparse

    parsed = urlparse(ollama_host)
    if parsed.scheme not in ("http", "https"):
        console.print(f"[red]Invalid OLLAMA_HOST scheme: {parsed.scheme}. Must be http or https.[/red]")
        console.print("[dim]Falling back to http://localhost:11434[/dim]")
        ollama_host = "http://localhost:11434"
    elif parsed.hostname not in ("localhost", "127.0.0.1", "::1", None):
        console.print(f"[yellow]Warning: OLLAMA_HOST points to remote host: {parsed.hostname}[/yellow]")

    try:
        import urllib.request

        urllib.request.urlopen(f"{ollama_host}/api/tags", timeout=2)
        console.print(f"[green]✓ Ollama server is running at {ollama_host}[/green]")
    except Exception:
        console.print(f"[yellow]⚠️  Ollama server not running at {ollama_host}[/yellow]")
        console.print("[dim]Start with: ollama serve[/dim]")

    # Query installed models to pick smart defaults
    installed_models: list[str] = []
    try:
        import json
        import urllib.request as req

        resp = req.urlopen(f"{ollama_host}/api/tags", timeout=3)
        installed_models = [m["name"] for m in json.loads(resp.read()).get("models", [])]
    except Exception:
        pass

    # Pick best smart model from installed models (prefer larger coder models)
    smart_candidates = [
        "qwen2.5-coder:7b",
        "qwen2.5-coder:3b",
        "codellama:7b",
        "deepseek-coder:6.7b",
        "starcoder2:7b",
    ]
    # Fresh install: default to 3b (faster download, lower footprint).
    # If user already has a larger model installed, use that instead.
    default_model = "qwen2.5-coder:3b"
    for candidate in smart_candidates:
        if candidate in installed_models:
            default_model = candidate
            break

    model = default_model
    if is_interactive:
        model = Prompt.ask("Select model", default=default_model)

    # Check if selected model is actually installed — offer to pull if not
    missing_models = []
    if model not in installed_models:
        missing_models.append(model)

    if missing_models:
        from warden.services.local_model_manager import LocalModelManager

        manager = LocalModelManager()
        console.print(f"\n[bold yellow]⚠️  Missing models: {', '.join(missing_models)}[/bold yellow]")

        for m in missing_models:
            should_pull = True
            if is_interactive:
                should_pull = Confirm.ask(f"Pull model '{m}' now?", default=True)

            if should_pull:
                console.print(f"[dim]⬇️  Pulling {m}...[/dim]")
                success = manager.pull_model(m, show_progress=is_interactive)
                if success:
                    console.print(f"[green]✓ {m} downloaded[/green]")
                else:
                    console.print(f"[yellow]⚠️  Pull failed. Run manually: ollama pull {m}[/yellow]")
            else:
                console.print(f"[yellow]   Run manually: ollama pull {m}[/yellow]")
    else:
        console.print(f"[green]✓ Model '{model}' is installed[/green]")

    llm_config = {
        "provider": "ollama",
        "model": model,
        "timeout": 300,
        "use_local_llm": True,
        # fast_model is intentionally omitted: Ollama IS the primary (smart) provider.
        # Other fast-tier providers (Groq, Claude Code, etc.) use their own default models.
    }

    env_vars = {"OLLAMA_HOST": ollama_host}

    return llm_config, env_vars


def configure_claude_code() -> tuple[dict, dict]:
    """
    Configure Claude Code (local Claude Code CLI).
    Checks if Claude Code is installed and authenticated.
    Returns (llm_config, env_vars).
    """
    console.print("\n[bold cyan]🖥️  Configuring Claude Code (Local)[/bold cyan]")

    # Check if Claude Code is installed
    claude_path = shutil.which("claude")

    is_interactive = sys.stdin.isatty() and os.environ.get("WARDEN_NON_INTERACTIVE") != "true"

    if not claude_path:
        console.print("[yellow]⚠️  Claude Code CLI is not installed.[/yellow]")
        console.print("[dim]Install it from: https://docs.anthropic.com/en/docs/claude-code[/dim]")
        console.print("[dim]Or run: npm install -g @anthropic-ai/claude-code[/dim]")

        if is_interactive and Confirm.ask("Try a different provider?", default=True):
            return _fallback_to_cloud_provider()

        # Non-interactive: return with disabled config
        return {"provider": "claude_code", "model": "claude-sonnet-4-20250514", "enabled": False}, {}

    console.print(f"[green]✓ Claude Code found at: {claude_path}[/green]")

    # Verify authentication
    console.print("[dim]Checking authentication...[/dim]")
    try:
        result = subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            version = result.stdout.strip()
            console.print(f"[green]✓ Claude Code version: {version}[/green]")
        else:
            console.print("[yellow]⚠️  Claude Code may not be authenticated.[/yellow]")
            console.print("[dim]Run 'claude' to authenticate.[/dim]")
    except (subprocess.TimeoutExpired, Exception) as e:
        console.print(f"[yellow]⚠️  Could not verify Claude Code: {e}[/yellow]")

    # Select mode
    mode = "cli"
    if is_interactive:
        console.print("\n[bold]Select Claude Code mode:[/bold]")
        console.print("  [1] CLI - Use Claude Code CLI (default, most compatible)")
        console.print("  [2] SDK - Use Claude Agent SDK (requires claude-code-sdk package)")

        mode_choice = Prompt.ask("Select mode", choices=["1", "2"], default="1")
        mode = "cli" if mode_choice == "1" else "sdk"

    console.print(f"\n[green]✓ Claude Code configured with mode: {mode}[/green]")
    console.print("[dim]💡 Model selection is controlled by `claude config`[/dim]")

    llm_config = {
        "provider": "claude_code",
        "mode": mode,
        "model": "claude-code-default",  # Placeholder - actual model set in claude config
        "smart_model": "claude-code-default",
        "fast_model": "claude-code-default",
        "timeout": 300,
        "use_local_llm": False,  # Claude Code is not the same as Ollama
    }

    # No env vars needed - auto-detection handles everything
    env_vars = {}

    return llm_config, env_vars


def configure_codex() -> tuple[dict, dict]:
    """
    Configure Codex (local Codex CLI).
    Checks if Codex is installed, then writes a minimal CLI-based config.
    Returns (llm_config, env_vars).
    """
    console.print("\n[bold cyan]🧩  Configuring Codex (Local)[/bold cyan]")

    codex_path = shutil.which("codex")
    is_interactive = sys.stdin.isatty() and os.environ.get("WARDEN_NON_INTERACTIVE") != "true"

    if not codex_path:
        console.print("[yellow]⚠️  Codex CLI not found on PATH.[/yellow]")
        console.print("[dim]Install it via: npm install -g @openai/codex[/dim]")

        if is_interactive and Confirm.ask("Try a different provider?", default=True):
            return _fallback_to_cloud_provider()

        return {"provider": "codex", "model": "codex-local", "enabled": False}, {}

    console.print(f"[green]✓ Codex CLI found at: {codex_path}[/green]")

    try:
        result = subprocess.run(["codex", "--version"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            console.print(f"[green]✓ Codex version: {result.stdout.strip()}[/green]")
        else:
            console.print("[yellow]⚠️  Could not verify Codex version.[/yellow]")
    except (subprocess.TimeoutExpired, Exception) as e:
        console.print(f"[yellow]⚠️  Could not verify Codex: {e}[/yellow]")

    console.print("[dim]💡 Codex operates via file-based CLI — no API key required.[/dim]")

    llm_config = {
        "provider": "codex",
        "model": "codex-local",
        "smart_model": "codex-local",
        "fast_model": "codex-local",
        "endpoint": "cli",
        "timeout": 120,
        "use_local_llm": True,
    }

    return llm_config, {}


def _fallback_to_cloud_provider() -> tuple[dict, dict]:
    """Fallback when Ollama setup fails."""
    is_interactive = sys.stdin.isatty() and os.environ.get("WARDEN_NON_INTERACTIVE") != "true"

    if not is_interactive:
        # Non-interactive mode: return disabled config (for CI/testing)
        console.print("[dim]Non-interactive mode: Skipping cloud provider setup[/dim]")
        return {"provider": "ollama", "model": "qwen2.5-coder:7b", "enabled": False}, {}

    console.print("\n[bold yellow]Selecting alternative cloud provider...[/bold yellow]")

    # Show only cloud options
    for key in ["2", "3", "4", "7"]:
        p = LLM_PROVIDERS[key]
        console.print(f"  [{key}] {p['emoji']} {p['name']} - {p['description']}")

    choice = Prompt.ask("Select cloud provider", choices=["2", "3", "4", "7"], default="7")

    provider = LLM_PROVIDERS[choice]
    return configure_cloud_provider(provider)


def configure_cloud_provider(provider: dict) -> tuple[dict, dict]:
    """
    Configure a cloud LLM provider.
    Prompts for API key and validates format.
    Returns (llm_config, env_vars).
    """
    provider_name = provider["name"]
    key_var = provider["key_var"]
    key_prefix = provider.get("key_prefix", "")
    default_model = provider["default_model"]

    is_interactive = sys.stdin.isatty() and os.environ.get("WARDEN_NON_INTERACTIVE") != "true"

    console.print(f"\n[bold cyan]☁️  Configuring {provider_name}[/bold cyan]")

    # Check if key already exists in environment
    existing_key = os.environ.get(key_var)
    if existing_key:
        masked = existing_key[:8] + "..." + existing_key[-4:] if len(existing_key) > 12 else "****"
        console.print(f"[green]✓ Found existing {key_var}: {masked}[/green]")
        if is_interactive and not Confirm.ask("Use existing key?", default=True):
            existing_key = None

    env_vars = {}

    if not existing_key:
        if not is_interactive:
            # Non-interactive: no key and no prompt possible — skip gracefully
            console.print(f"[yellow]⚠️  {key_var} not set. Skipping cloud provider setup.[/yellow]")
            return {"provider": "ollama", "model": "qwen2.5-coder:7b", "enabled": False}, {}

        # Prompt for API key
        console.print("[dim]Get your API key from the provider's dashboard.[/dim]")
        if key_prefix:
            console.print(f"[dim]Key should start with: {key_prefix}[/dim]")

        while True:
            api_key = Prompt.ask(f"Enter {provider_name} API Key", password=True)

            # FAST FAIL: Check prefix
            if key_prefix and not api_key.startswith(key_prefix):
                console.print(f"[yellow]⚠️  Key must start with '{key_prefix}'[/yellow]")
                if Confirm.ask("Use this key anyway?", default=False):
                    break
            # BASIC SANITY: Check length
            elif len(api_key) < 8:
                console.print("[red]❌ Key looks too short.[/red]")
            else:
                break

        env_vars[key_var] = api_key

    # Model selection
    model = default_model
    if is_interactive:
        model = Prompt.ask("Select model", default=default_model)

    llm_config = {"provider": provider["id"], "model": model, "timeout": 300}

    # Ask about local LLM for fast tier
    enable_hybrid = not is_interactive or Confirm.ask(
        "Enable Ollama for fast/cheap checks? (Hybrid mode)", default=True
    )
    if enable_hybrid:
        llm_config["use_local_llm"] = True
        llm_config["fast_model"] = "qwen2.5-coder:3b"
        if is_interactive:
            console.print("[green]✓ Hybrid mode enabled (Cloud for smart, Local for fast)[/green]")

    return llm_config, env_vars


def configure_azure() -> tuple[dict, dict]:
    """
    Configure Azure OpenAI with all required parameters.
    Returns (llm_config, env_vars).
    """
    console.print("\n[bold cyan]☁️  Configuring Azure OpenAI[/bold cyan]")
    console.print("[dim]Azure OpenAI requires additional configuration.[/dim]\n")

    env_vars = {}

    # API Key
    api_key = Prompt.ask("Azure OpenAI API Key", password=True)
    env_vars["AZURE_OPENAI_API_KEY"] = api_key

    # Endpoint
    endpoint = Prompt.ask("Azure Endpoint URL", default="https://your-resource.openai.azure.com")
    env_vars["AZURE_OPENAI_ENDPOINT"] = endpoint

    # Deployment Name
    deployment = Prompt.ask("Deployment Name", default="gpt-4o")
    env_vars["AZURE_OPENAI_DEPLOYMENT_NAME"] = deployment

    # API Version
    api_version = Prompt.ask("API Version", default="2024-02-15-preview")

    llm_config = {
        "provider": "azure",
        "model": deployment,
        "timeout": 300,
        "azure": {
            "endpoint": "${AZURE_OPENAI_ENDPOINT}",
            "api_key": "${AZURE_OPENAI_API_KEY}",
            "deployment_name": "${AZURE_OPENAI_DEPLOYMENT_NAME}",
            "api_version": api_version,
        },
    }

    return llm_config, env_vars


def configure_llm(existing_config: dict | None = None) -> tuple[dict, dict]:
    """
    Main LLM configuration flow.
    Step 1: Provider selection
    Step 2: Provider-specific configuration
    Returns (llm_config, env_vars).
    """
    if existing_config is None:
        existing_config = {}

    # Step 1: Select provider
    provider = select_llm_provider()

    # Step 2: Provider-specific configuration
    if provider["id"] == "ollama":
        return configure_ollama()
    elif provider["id"] == "azure":
        return configure_azure()
    elif provider["id"] == "claude_code":
        return configure_claude_code()
    elif provider["id"] == "codex":
        return configure_codex()
    else:
        # For non-interactive fallback to deepseek or whatever if key exists,
        # but usually we want ollama for zero-config.
        return configure_cloud_provider(provider)


# =============================================================================
# CI/CD Configuration
# =============================================================================


def select_ci_provider() -> dict:
    """
    Display CI provider selection UI.
    Returns selected CI provider info.
    """
    console.print("\n[bold cyan]🔄 Step 2: CI/CD Integration[/bold cyan]")
    console.print("[dim]Automatically scan code on every push/PR.[/dim]\n")

    for key, ci in CI_PROVIDERS.items():
        if ci["id"] == "skip":
            console.print(f"  [{key}] ⏭️  {ci['name']}")
        else:
            console.print(f"  [{key}] {ci['name']}")

    console.print()

    is_interactive = sys.stdin.isatty() and os.environ.get("WARDEN_NON_INTERACTIVE") != "true"

    choice = "3"  # Default: skip
    if is_interactive:
        choice = Prompt.ask("Select CI provider", choices=list(CI_PROVIDERS.keys()), default="3")

    return CI_PROVIDERS[choice]


def configure_ci_workflow(ci_provider: dict, llm_config: dict, project_root: Path, branch: str = "main") -> bool:
    """
    Generate CI workflow files from templates.

    Creates three specialized workflows for GitHub Actions:
    - warden-pr.yml: PR scans (--ci --diff)
    - warden-nightly.yml: Nightly full scans (--update-baseline)
    - warden-release.yml: Release audits (--level deep)

    For GitLab, creates a single .gitlab-ci.yml with all stages.

    Returns True if workflows were created.
    """
    if ci_provider["id"] == "skip":
        console.print("[dim]CI/CD configuration skipped. Run 'warden init --ci' later.[/dim]")
        return False

    console.print(f"\n[bold cyan]📝 Generating {ci_provider['name']} Workflows[/bold cyan]")
    console.print("[dim]Creating PR, Nightly, and Release workflows...[/dim]")

    # Prepare template variables
    provider_id = llm_config.get("provider", "ollama")
    fast_provider_id = llm_config.get("fast_provider", "ollama")
    fast_model = llm_config.get("fast_model", "qwen2.5-coder:3b")

    # Determine if Ollama is needed (smart tier OR fast tier)
    needs_ollama = provider_id == "ollama" or fast_provider_id == "ollama"

    # Build environment variables section for CI
    ci_env_vars_parts: list[str] = []

    # Smart tier API key
    if provider_id != "ollama":
        for p in LLM_PROVIDERS.values():
            if p["id"] == provider_id:
                key_var = p.get("key_var")
                if key_var:
                    ci_env_vars_parts.append(f"      {key_var}: ${{{{ secrets.{key_var} }}}}")
                break

    # Fast tier API key (only if different provider and not ollama)
    if fast_provider_id not in ("ollama", "none", provider_id):
        for p in LLM_PROVIDERS.values():
            if p["id"] == fast_provider_id:
                key_var = p.get("key_var")
                if key_var:
                    ci_env_vars_parts.append(f"      {key_var}: ${{{{ secrets.{key_var} }}}}")
                break

    # Ollama host env var
    if needs_ollama:
        ci_env_vars_parts.append("      OLLAMA_HOST: http://localhost:11434")

    ci_env_vars = "\n".join(ci_env_vars_parts)

    # Ollama setup step — install + serve + pull the fast model
    if needs_ollama:
        ollama_setup = f"""      - name: Setup Ollama
        run: |
          curl -fsSL https://ollama.com/install.sh | sh
          ollama serve &
          echo "Waiting for Ollama to be ready..."
          for i in {{1..30}}; do
            if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
              echo "Ollama is ready!"
              break
            fi
            echo "Attempt $i/30: Ollama not ready yet..."
            sleep 1
          done
          ollama pull {fast_model}

"""
    else:
        ollama_setup = ""

    # Define workflows to generate based on CI provider
    if ci_provider["id"] == "github":
        workflows = [
            ("warden-pr.yml", ".github/workflows/warden-pr.yml"),
            ("warden-nightly.yml", ".github/workflows/warden-nightly.yml"),
            ("warden-release.yml", ".github/workflows/warden-release.yml"),
        ]
    elif ci_provider["id"] == "gitlab":
        # GitLab uses single .gitlab-ci.yml with stages
        workflows = [
            ("gitlab.yml", ".gitlab-ci.yml"),
        ]
    else:
        workflows = []

    import importlib.resources

    created_count = 0

    for template_name, target_rel_path in workflows:
        target_path = project_root / target_rel_path

        # Load template
        try:
            template_content = importlib.resources.read_text("warden.templates.workflows", template_name)
        except Exception as e:
            console.print(f"[yellow]Warning: Template {template_name} not found: {e}[/yellow]")
            continue

        # Apply template substitutions
        content = template_content.format(
            branch=branch, ci_llm_provider=provider_id, ci_env_vars=ci_env_vars, ollama_setup=ollama_setup
        )

        # Create target directory if needed
        target_path.parent.mkdir(parents=True, exist_ok=True)

        # Write workflow file
        with open(target_path, "w") as f:
            f.write(content)

        console.print(f"[green]✓ Created {target_path}[/green]")
        created_count += 1

    # Show secret configuration hint
    if provider_id != "ollama":
        console.print(f"\n[yellow]⚠️  Remember to add secrets to your {ci_provider['name']}:[/yellow]")
        if provider_id == "azure":
            console.print("   - AZURE_OPENAI_API_KEY")
            console.print("   - AZURE_OPENAI_ENDPOINT")
            console.print("   - AZURE_OPENAI_DEPLOYMENT_NAME")
        else:
            for p in LLM_PROVIDERS.values():
                if p["id"] == provider_id:
                    console.print(f"   - {p.get('key_var', 'API_KEY')}")
                    break

    # Show workflow summary for GitHub
    if ci_provider["id"] == "github" and created_count > 0:
        console.print(f"\n[bold green]✓ Created {created_count} CI workflow(s):[/bold green]")
        console.print("   [cyan]warden-pr.yml[/cyan]      → PR scans (--ci --diff)")
        console.print("   [cyan]warden-nightly.yml[/cyan] → Nightly baseline updates")
        console.print("   [cyan]warden-release.yml[/cyan] → Release security audits")

    return created_count > 0


# =============================================================================
# AI Tool Files Generation
# =============================================================================


def generate_ai_tool_files(project_root: Path, llm_config: dict) -> None:
    """
    Generate AI tool integration files from templates.
    Creates: CLAUDE.md, .cursorrules, ai_status.md, .env.example
    """
    console.print("\n[bold cyan]🤖 Step 3: AI Tool Integration[/bold cyan]")
    console.print("[dim]Setting up files for Claude Code, Cursor, etc.[/dim]\n")

    warden_dir = project_root / ".warden"
    warden_dir.mkdir(exist_ok=True)

    import importlib.resources

    # 1. Create CLAUDE.md in project root
    # 1. Create/Update CLAUDE.md in project root
    try:
        claude_md_path = project_root / "CLAUDE.md"

        # Post-Setup Content: How to USE Warden
        claude_content = """# Role: Warden Security Expert

## 🛡️ SYSTEM STATUS: ACTIVE
**Warden is configured and running.**

## 🤖 YOUR PRIMARY DIRECTIVE
You are responsible for the security and code quality of this project.

**OPERATIONAL PROTOCOL:**
1. **Analyze**: Run `warden scan` after significant code changes.
2. **Consult**: Read `.warden/reports/warden_report.json` to see current findings.
3. **Fix**: When fixing issues, verify them by running `warden scan --file <path>`.

**COMMANDS:**
- `/scan`: `warden scan`
- `/status`: `warden status`
- `/help`: `warden --help`

**Do not ask for setup instructions.** The system is already online.
"""
        with open(claude_md_path, "w") as f:
            f.write(claude_content)
        console.print(f"[green]✓ Updated {claude_md_path} (Security Protocols Active)[/green]")

    except Exception as e:
        console.print(f"[yellow]Warning: Could not update CLAUDE.md: {e}[/yellow]")

    # 2. Create/Update .cursorrules
    try:
        cursorrules_template = importlib.resources.read_text("warden.templates", "cursorrules")
        cursorrules_path = project_root / ".cursorrules"

        if not cursorrules_path.exists():
            with open(cursorrules_path, "w") as f:
                f.write(cursorrules_template)
            console.print(f"[green]✓ Created {cursorrules_path}[/green]")
        else:
            # Check if Warden rules already injected
            existing_content = cursorrules_path.read_text()
            if "Warden" not in existing_content:
                with open(cursorrules_path, "a") as f:
                    f.write("\n\n" + cursorrules_template)
                console.print(f"[green]✓ Updated {cursorrules_path}[/green]")
            else:
                console.print("[dim].cursorrules already has Warden rules, skipping.[/dim]")
    except Exception as e:
        console.print(f"[yellow]Warning: Could not create .cursorrules: {e}[/yellow]")

    # 3. Create ai_status.md
    try:
        status_template = importlib.resources.read_text("warden.templates", "ai_status.md")
        status_path = warden_dir / "ai_status.md"

        # Fill template with initial values
        status_content = status_template.format(
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            status="PENDING",
            score="?",
            status_details="Run `warden scan` to perform initial analysis.",
        )

        with open(status_path, "w") as f:
            f.write(status_content)
        console.print(f"[green]✓ Created {status_path}[/green]")
    except Exception as e:
        console.print(f"[yellow]Warning: Could not create ai_status.md: {e}[/yellow]")

    # 4. Create/Update .env.example
    try:
        env_template = importlib.resources.read_text("warden.templates", "env.example")
        env_example_path = project_root / ".env.example"

        lines: list[str] = []
        if env_example_path.exists():
            lines = env_example_path.read_text().splitlines()
        else:
            lines = env_template.splitlines()

        def ensure_line(key: str):
            nonlocal lines
            if not any(l.split("=")[0] == key for l in lines if "=" in l):
                lines.append(f"{key}=")

        # Common provider override used in CI/local split
        ensure_line("WARDEN_LLM_PROVIDER")

        with open(env_example_path, "w") as f:
            f.write("\n".join(lines) + "\n")
        console.print(f"[green]✓ Updated {env_example_path}[/green]")
    except Exception as e:
        console.print(f"[yellow]Warning: Could not update .env.example: {e}[/yellow]")

    # 5. Create AI_RULES.md (detailed protocol)
    try:
        rules_template = importlib.resources.read_text("warden.templates", "AI_RULES.md")
        rules_path = warden_dir / "AI_RULES.md"

        with open(rules_path, "w") as f:
            f.write(rules_template)
        console.print(f"[green]✓ Created {rules_path}[/green]")
    except Exception:
        # Fallback if template not found
        fallback_rules = """# Warden AI Protocol

## Startup
1. Read `.warden/ai_status.md` first
2. If status is FAIL: Fix issues before other work
3. If status is PENDING: Run `warden scan`

## During Development
1. After code changes: Run `warden scan`
2. Before commit: Ensure PASS status
3. Report score after significant changes

## Commands
- `warden scan` - Full project scan
- `warden scan --file <path>` - Single file scan
- `warden status` - Quick status check
"""
        rules_path = warden_dir / "AI_RULES.md"
        with open(rules_path, "w") as f:
            f.write(fallback_rules)
        console.print(f"[green]✓ Created {rules_path} (fallback)[/green]")


def configure_vector_db() -> dict:
    """Configure Vector Database settings interactively."""
    console.print("\n[bold cyan]🗄️  Vector Database Configuration[/bold cyan]")
    is_interactive = sys.stdin.isatty() and os.environ.get("WARDEN_NON_INTERACTIVE") != "true"

    vector_db_choice = "local (chromadb)"
    if is_interactive:
        vector_db_choice = Prompt.ask(
            "Select Vector Database Provider",
            choices=["local (chromadb)", "cloud (qdrant/pinecone)"],
            default="local (chromadb)",
        )

    safe_name = "".join(c if c.isalnum() else "_" for c in Path.cwd().name).lower()
    collection_name = f"warden_{safe_name}"

    if vector_db_choice == "local (chromadb)":
        return {
            "enabled": True,
            "provider": "local",
            "database": "chromadb",
            "chroma_path": ".warden/embeddings",
            "collection_name": collection_name,
            "max_context_tokens": 4000,
        }
    else:
        # Simplified cloud setup for brevity in helper
        return {
            "enabled": True,
            "provider": "qdrant",
            "url": "${QDRANT_URL}",
            "api_key": "${QDRANT_API_KEY}",
            "collection_name": collection_name,
        }


def _generate_agent_protocol(project_root: Path) -> Path:
    """Generate .warden/AI_RULES.md agent protocol file."""
    warden_dir = project_root / ".warden"
    warden_dir.mkdir(exist_ok=True)
    rules_path = warden_dir / "AI_RULES.md"

    try:
        import importlib.resources

        template_content = importlib.resources.read_text("warden.templates", "AI_RULES.md")
    except Exception:
        template_content = """# Warden Agent Protocol

## 🚀 Setup Assistance
**IF** the user is asking for help setting up Warden:
1. READ `warden://setup/guide` immediately.
2. Follow the interview protocol defined there.
3. Use `warden_configure` to apply settings.

## 🛡️ Development Workflow
1. Run `warden scan` after every edit.
2. Fix all issues before completing tasks.
3. Use `warden_status` to check health.
"""

    with open(rules_path, "w") as f:
        f.write(template_content)
    console.print(f"[green]✓ Created Agent Protocol: {rules_path}[/green]")
    return rules_path


def _configure_ide_rules(project_root: Path, rules_path: Path) -> None:
    """Inject Warden protocol into .cursorrules / .windsurfrules."""
    rule_files = [".cursorrules", ".windsurfrules"]
    found_rule_file = False

    instruction = (
        f"\n\n# Warden Agent Protocol\n"
        f"# IMPORTANT: You MUST follow the rules in {rules_path}\n"
        f"# Run 'warden scan' to verify your work.\n"
    )

    for rf in rule_files:
        rf_path = project_root / rf
        if rf_path.exists():
            content = rf_path.read_text()
            if "Warden Agent Protocol" not in content:
                with open(rf_path, "a") as f:
                    f.write(instruction)
                console.print(f"[green]✓ Injected rules into {rf}[/green]")
            else:
                console.print(f"[dim]Rules already present in {rf}[/dim]")
            found_rule_file = True

    if not found_rule_file:
        default_rules = project_root / ".cursorrules"
        with open(default_rules, "w") as f:
            f.write(instruction)
        console.print(f"[green]✓ Created {default_rules}[/green]")


def _configure_claude_hooks(project_root: Path) -> None:
    """Create .claude/settings.json with SessionStart hook."""
    claude_dir = project_root / ".claude"
    claude_dir.mkdir(exist_ok=True)
    settings_path = claude_dir / "settings.json"

    if not settings_path.exists():
        hooks_config = {
            "hooks": {
                "SessionStart": [
                    {
                        "matcher": "startup",
                        "hooks": [{"type": "command", "command": "cat $CLAUDE_PROJECT_DIR/.warden/AI_RULES.md"}],
                    }
                ]
            }
        }
        with open(settings_path, "w") as f:
            json.dump(hooks_config, f, indent=2)
        console.print(f"[green]✓ Created Claude Hooks: {settings_path}[/green]")


def _resolve_warden_executable() -> str:
    """Resolve absolute path to the warden CLI binary."""
    # Priority 1: Current venv
    venv_warden = Path(sys.prefix) / "bin" / "warden"
    if venv_warden.exists():
        return str(venv_warden)

    # Priority 2: System PATH
    which_warden = shutil.which("warden")
    if which_warden:
        return which_warden

    # Priority 3: Common install locations (GUI apps lack user PATH)
    common_paths = [
        Path("/opt/homebrew/bin/warden"),
        Path("/usr/local/bin/warden"),
        Path.home() / ".local/bin/warden",
    ]
    for p in common_paths:
        if p.exists():
            return str(p)

    console.print("[yellow]Warning: Could not resolve absolute path for 'warden'. Using relative path.[/yellow]")
    return "warden"


def _configure_mcp_servers(project_root: Path) -> None:
    """Register warden MCP server in Cursor, Claude Desktop, Claude Code, Gemini."""
    warden_abs = _resolve_warden_executable()

    mcp_config_entry = {
        "command": warden_abs,
        "args": ["serve", "mcp"],
        "env": {"ProjectRoot": str(project_root.resolve())},
    }

    configs_to_update = [
        Path.home() / ".cursor" / "mcp.json",
        Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json",
        Path.home() / ".config" / "claude-code" / "mcp_settings.json",
        Path.home() / ".gemini" / "antigravity" / "mcp_config.json",
    ]

    for cfg_path in configs_to_update:
        if cfg_path.exists():
            try:
                content = cfg_path.read_text().strip()
                data = json.loads(content) if content else {}

                if "mcpServers" not in data:
                    data["mcpServers"] = {}

                data["mcpServers"]["warden"] = mcp_config_entry

                with open(cfg_path, "w") as f:
                    json.dump(data, f, indent=2)
                console.print(f"[green]✓ Configured MCP in {cfg_path.name}[/green]")

            except Exception as e:
                console.print(f"[red]Failed to update {cfg_path.name}: {e}[/red]")


def configure_agent_tools(project_root: Path) -> None:
    """
    Configure project for AI Agents (Cursor, Claude Desktop, Claude Code).

    Orchestrates four independent steps:
    1. Generate .warden/AI_RULES.md protocol file
    2. Inject rules into IDE config (.cursorrules / .windsurfrules)
    3. Create Claude Code hooks (.claude/settings.json)
    4. Register warden MCP server in all supported tools
    """
    console.print("\n[bold cyan]🤖 Configuring Agent Tools (Cursor / Claude)[/bold cyan]")

    rules_path = _generate_agent_protocol(project_root)
    _configure_ide_rules(project_root, rules_path)
    _configure_claude_hooks(project_root)
    _configure_mcp_servers(project_root)
