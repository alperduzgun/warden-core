"""
Initialization Helpers for Warden CLI.
Handles interactive configuration prompts with improved UX.
"""

import os
import sys
import subprocess
import shutil
import json
from pathlib import Path
from datetime import datetime
from rich.console import Console
from rich.prompt import Prompt, Confirm
from rich.panel import Panel
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
        "default_model": "qwen2.5-coder:7b"
    },
    "2": {
        "id": "anthropic",
        "name": "Anthropic Claude",
        "description": "Best quality, recommended for production",
        "emoji": "🧠",
        "requires_key": True,
        "key_var": "ANTHROPIC_API_KEY",
        "key_prefix": "sk-ant-",
        "default_model": "claude-sonnet-4-20250514"
    },
    "3": {
        "id": "openai",
        "name": "OpenAI",
        "description": "Popular choice, good balance",
        "emoji": "🤖",
        "requires_key": True,
        "key_var": "OPENAI_API_KEY",
        "key_prefix": "sk-",
        "default_model": "gpt-4o"
    },
    "4": {
        "id": "groq",
        "name": "Groq",
        "description": "Fast & cheap, great for CI/CD",
        "emoji": "⚡",
        "requires_key": True,
        "key_var": "GROQ_API_KEY",
        "key_prefix": "gsk_",
        "default_model": "llama-3.3-70b-versatile"
    },
    "5": {
        "id": "azure",
        "name": "Azure OpenAI",
        "description": "Enterprise, compliance-ready",
        "emoji": "☁️",
        "requires_key": True,
        "key_var": "AZURE_OPENAI_API_KEY",
        "default_model": "gpt-4o"
    },
    "6": {
        "id": "deepseek",
        "name": "DeepSeek",
        "description": "Budget-friendly alternative",
        "emoji": "🔍",
        "requires_key": True,
        "key_var": "DEEPSEEK_API_KEY",
        "default_model": "deepseek-coder"
    }
}

CI_PROVIDERS = {
    "1": {
        "id": "github",
        "name": "GitHub Actions",
        "template": "github.yml",
        "target_path": ".github/workflows/warden.yml"
    },
    "2": {
        "id": "gitlab",
        "name": "GitLab CI",
        "template": "gitlab.yml",
        "target_path": ".gitlab-ci.yml"
    },
    "3": {
        "id": "skip",
        "name": "Skip (Configure Later)",
        "template": None,
        "target_path": None
    }
}


def select_llm_provider() -> dict:
    """
    Display 6-option LLM provider selection UI.
    Returns selected provider info.
    """
    console.print("\n[bold cyan]🧠 Step 1: Select LLM Provider[/bold cyan]")
    console.print("[dim]Warden requires an LLM for AI-powered analysis.[/dim]\n")

    # Build selection table
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Option", style="bold cyan", width=3)
    table.add_column("Provider", style="bold white", width=20)
    table.add_column("Description", style="dim")

    for key, provider in LLM_PROVIDERS.items():
        table.add_row(
            f"[{key}]",
            f"{provider['emoji']} {provider['name']}",
            provider['description']
        )

    console.print(table)
    console.print()

    is_interactive = sys.stdin.isatty() and os.environ.get("WARDEN_NON_INTERACTIVE") != "true"
    
    choice = "1"
    if is_interactive:
        choice = Prompt.ask(
            "Select provider",
            choices=list(LLM_PROVIDERS.keys()),
            default="1"
        )

    return LLM_PROVIDERS[choice]


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
                subprocess.run(
                    ["bash", "-c", "curl -fsSL https://ollama.com/install.sh | sh"],
                    check=True
                )
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

    try:
        import urllib.request
        urllib.request.urlopen(f"{ollama_host}/api/tags", timeout=2)
        console.print(f"[green]✓ Ollama server is running at {ollama_host}[/green]")
    except Exception:
        console.print(f"[yellow]⚠️  Ollama server not running at {ollama_host}[/yellow]")
        console.print("[dim]Start with: ollama serve[/dim]")

    # Model selection
    default_model = "qwen2.5-coder:7b"
    model = default_model
    if is_interactive:
        model = Prompt.ask("Select model", default=default_model)

    # Check if model is available
    console.print(f"[dim]Tip: Run 'ollama pull {model}' if not already downloaded.[/dim]")

    llm_config = {
        "provider": "ollama",
        "model": model,
        "timeout": 300,
        "use_local_llm": True,
        "fast_model": "qwen2.5-coder:0.5b"
    }

    env_vars = {
        "OLLAMA_HOST": ollama_host
    }

    return llm_config, env_vars


def _fallback_to_cloud_provider() -> tuple[dict, dict]:
    """Fallback when Ollama setup fails."""
    console.print("\n[bold yellow]Selecting alternative cloud provider...[/bold yellow]")
    # Show only cloud options
    for key in ["2", "3", "4"]:
        p = LLM_PROVIDERS[key]
        console.print(f"  [{key}] {p['emoji']} {p['name']} - {p['description']}")

    choice = Prompt.ask("Select cloud provider", choices=["2", "3", "4"], default="4")
    provider = LLM_PROVIDERS[choice]
    return configure_cloud_provider(provider)


def configure_cloud_provider(provider: dict) -> tuple[dict, dict]:
    """
    Configure a cloud LLM provider.
    Prompts for API key and validates format.
    Returns (llm_config, env_vars).
    """
    provider_name = provider['name']
    key_var = provider['key_var']
    key_prefix = provider.get('key_prefix', '')
    default_model = provider['default_model']

    console.print(f"\n[bold cyan]☁️  Configuring {provider_name}[/bold cyan]")

    # Check if key already exists in environment
    existing_key = os.environ.get(key_var)
    if existing_key:
        masked = existing_key[:8] + "..." + existing_key[-4:] if len(existing_key) > 12 else "****"
        console.print(f"[green]✓ Found existing {key_var}: {masked}[/green]")
        if not Confirm.ask("Use existing key?", default=True):
            existing_key = None

    env_vars = {}

    if not existing_key:
        # Prompt for API key
        console.print(f"[dim]Get your API key from the provider's dashboard.[/dim]")
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
    model = Prompt.ask("Select model", default=default_model)

    llm_config = {
        "provider": provider['id'],
        "model": model,
        "timeout": 300
    }

    # Ask about local LLM for fast tier
    if Confirm.ask("Enable Ollama for fast/cheap checks? (Hybrid mode)", default=True):
        llm_config["use_local_llm"] = True
        llm_config["fast_model"] = "qwen2.5-coder:0.5b"
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
    endpoint = Prompt.ask(
        "Azure Endpoint URL",
        default="https://your-resource.openai.azure.com"
    )
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
            "api_version": api_version
        }
    }

    return llm_config, env_vars


def configure_llm(existing_config: dict = None) -> tuple[dict, dict]:
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
    if provider['id'] == 'ollama':
        return configure_ollama()
    elif provider['id'] == 'azure':
        return configure_azure()
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
        if ci['id'] == 'skip':
            console.print(f"  [{key}] ⏭️  {ci['name']}")
        else:
            console.print(f"  [{key}] {ci['name']}")

    console.print()

    is_interactive = sys.stdin.isatty() and os.environ.get("WARDEN_NON_INTERACTIVE") != "true"
    
    choice = "3" # Default: skip
    if is_interactive:
        choice = Prompt.ask(
            "Select CI provider",
            choices=list(CI_PROVIDERS.keys()),
            default="3"
        )

    return CI_PROVIDERS[choice]


def configure_ci_workflow(
    ci_provider: dict,
    llm_config: dict,
    project_root: Path,
    branch: str = "main"
) -> bool:
    """
    Generate CI workflow files from templates.

    Creates three specialized workflows for GitHub Actions:
    - warden-pr.yml: PR scans (--ci --diff)
    - warden-nightly.yml: Nightly full scans (--update-baseline)
    - warden-release.yml: Release audits (--level deep)

    For GitLab, creates a single .gitlab-ci.yml with all stages.

    Returns True if workflows were created.
    """
    if ci_provider['id'] == 'skip':
        console.print("[dim]CI/CD configuration skipped. Run 'warden init --ci' later.[/dim]")
        return False

    console.print(f"\n[bold cyan]📝 Generating {ci_provider['name']} Workflows[/bold cyan]")
    console.print("[dim]Creating PR, Nightly, and Release workflows...[/dim]")

    # Prepare template variables
    provider_id = llm_config.get('provider', 'ollama')

    # Build environment variables section for CI
    ci_env_vars = ""
    if provider_id == 'ollama':
        ci_env_vars = "      OLLAMA_HOST: http://localhost:11434"
        ollama_setup = """      - name: Setup Ollama
        run: |
          curl -fsSL https://ollama.com/install.sh | sh
          ollama serve &
          sleep 5
          ollama pull qwen2.5-coder:0.5b

"""
    else:
        key_var = None
        for p in LLM_PROVIDERS.values():
            if p['id'] == provider_id:
                key_var = p.get('key_var')
                break

        if key_var:
            ci_env_vars = f"      {key_var}: ${{{{ secrets.{key_var} }}}}"

        ollama_setup = ""

    # Define workflows to generate based on CI provider
    if ci_provider['id'] == 'github':
        workflows = [
            ("warden-pr.yml", ".github/workflows/warden-pr.yml"),
            ("warden-nightly.yml", ".github/workflows/warden-nightly.yml"),
            ("warden-release.yml", ".github/workflows/warden-release.yml"),
        ]
    elif ci_provider['id'] == 'gitlab':
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
            template_content = importlib.resources.read_text(
                "warden.templates.workflows",
                template_name
            )
        except Exception as e:
            console.print(f"[yellow]Warning: Template {template_name} not found: {e}[/yellow]")
            continue

        # Apply template substitutions
        content = template_content.format(
            branch=branch,
            ci_llm_provider=provider_id,
            ci_env_vars=ci_env_vars,
            ollama_setup=ollama_setup
        )

        # Create target directory if needed
        target_path.parent.mkdir(parents=True, exist_ok=True)

        # Write workflow file
        with open(target_path, 'w') as f:
            f.write(content)

        console.print(f"[green]✓ Created {target_path}[/green]")
        created_count += 1

    # Show secret configuration hint
    if provider_id != 'ollama':
        console.print(f"\n[yellow]⚠️  Remember to add secrets to your {ci_provider['name']}:[/yellow]")
        if provider_id == 'azure':
            console.print("   - AZURE_OPENAI_API_KEY")
            console.print("   - AZURE_OPENAI_ENDPOINT")
            console.print("   - AZURE_OPENAI_DEPLOYMENT_NAME")
        else:
            for p in LLM_PROVIDERS.values():
                if p['id'] == provider_id:
                    console.print(f"   - {p.get('key_var', 'API_KEY')}")
                    break

    # Show workflow summary for GitHub
    if ci_provider['id'] == 'github' and created_count > 0:
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
    try:
        claude_md_template = importlib.resources.read_text("warden.templates", "CLAUDE.md")
        claude_md_path = project_root / "CLAUDE.md"

        if not claude_md_path.exists():
            with open(claude_md_path, 'w') as f:
                f.write(claude_md_template)
            console.print(f"[green]✓ Created {claude_md_path}[/green]")
        else:
            console.print(f"[dim]CLAUDE.md already exists, skipping.[/dim]")
    except Exception as e:
        console.print(f"[yellow]Warning: Could not create CLAUDE.md: {e}[/yellow]")

    # 2. Create/Update .cursorrules
    try:
        cursorrules_template = importlib.resources.read_text("warden.templates", "cursorrules")
        cursorrules_path = project_root / ".cursorrules"

        if not cursorrules_path.exists():
            with open(cursorrules_path, 'w') as f:
                f.write(cursorrules_template)
            console.print(f"[green]✓ Created {cursorrules_path}[/green]")
        else:
            # Check if Warden rules already injected
            existing_content = cursorrules_path.read_text()
            if "Warden" not in existing_content:
                with open(cursorrules_path, 'a') as f:
                    f.write("\n\n" + cursorrules_template)
                console.print(f"[green]✓ Updated {cursorrules_path}[/green]")
            else:
                console.print(f"[dim].cursorrules already has Warden rules, skipping.[/dim]")
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
            status_details="Run `warden scan` to perform initial analysis."
        )

        with open(status_path, 'w') as f:
            f.write(status_content)
        console.print(f"[green]✓ Created {status_path}[/green]")
    except Exception as e:
        console.print(f"[yellow]Warning: Could not create ai_status.md: {e}[/yellow]")

    # 4. Create .env.example
    try:
        env_template = importlib.resources.read_text("warden.templates", "env.example")
        env_example_path = project_root / ".env.example"

        if not env_example_path.exists():
            with open(env_example_path, 'w') as f:
                f.write(env_template)
            console.print(f"[green]✓ Created {env_example_path}[/green]")
    except Exception as e:
        console.print(f"[yellow]Warning: Could not create .env.example: {e}[/yellow]")

    # 5. Create AI_RULES.md (detailed protocol)
    try:
        rules_template = importlib.resources.read_text("warden.templates", "AI_RULES.md")
        rules_path = warden_dir / "AI_RULES.md"

        with open(rules_path, 'w') as f:
            f.write(rules_template)
        console.print(f"[green]✓ Created {rules_path}[/green]")
    except Exception as e:
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
        with open(rules_path, 'w') as f:
            f.write(fallback_rules)
        console.print(f"[green]✓ Created {rules_path} (fallback)[/green]")

def configure_vector_db() -> dict:
    """Configure Vector Database settings interactively."""
    console.print("\n[bold cyan]🗄️  Vector Database Configuration[/bold cyan]")
    is_interactive = sys.stdin.isatty() and os.environ.get("WARDEN_NON_INTERACTIVE") != "true"
    
    vector_db_choice = "local (chromadb)"
    if is_interactive:
        vector_db_choice = Prompt.ask("Select Vector Database Provider", choices=["local (chromadb)", "cloud (qdrant/pinecone)"], default="local (chromadb)")
        
    safe_name = "".join(c if c.isalnum() else "_" for c in Path.cwd().name).lower()
    collection_name = f"warden_{safe_name}"

    if vector_db_choice == "local (chromadb)":
        return {
             "enabled": True, "provider": "local", "database": "chromadb",
             "chroma_path": ".warden/embeddings", "collection_name": collection_name, "max_context_tokens": 4000
        }
    else:
        # Simplified cloud setup for brevity in helper
        return {
             "enabled": True, "provider": "qdrant", "url": "${QDRANT_URL}",
             "api_key": "${QDRANT_API_KEY}", "collection_name": collection_name,
        }


def configure_agent_tools(project_root: Path) -> None:
    """
    Configure project for AI Agents (Cursor, Claude Desktop).
    1. Generate AI_RULES.md
    2. Update .cursorrules or .windsurfrules
    3. Update MCP configuration
    """
    console.print("\n[bold cyan]🤖 Configuring Agent Tools (Cursor / Claude)[/bold cyan]")

    # 1. AI_RULES.md
    warden_dir = project_root / ".warden"
    warden_dir.mkdir(exist_ok=True)
    rules_path = warden_dir / "AI_RULES.md"

    # Built-in template
    try:
        # Attempt to read from package resources or relative path
        import importlib.resources
        template_content = importlib.resources.read_text("warden.templates", "AI_RULES.md")
    except Exception:
        # Fallback simplistic content if template is missing/moved
        template_content = "# Warden Protocol\n\n1. Run `warden scan` after every edit.\n2. Fix all issues before completing tasks.\n"

    with open(rules_path, "w") as f:
        f.write(template_content)
    console.print(f"[green]✓ Created Agent Protocol: {rules_path}[/green]")

    # 2. Update .cursorrules / .windsurfrules
    rule_files = [".cursorrules", ".windsurfrules"]
    found_rule_file = False

    instruction = f"\n\n# Warden Agent Protocol\n# IMPORTANT: You MUST follow the rules in {rules_path}\n# Run 'warden scan' to verify your work.\n"

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
        # Create .cursorrules by default if none exist
        default_rules = project_root / ".cursorrules"
        with open(default_rules, "w") as f:
            f.write(instruction)
        console.print(f"[green]✓ Created {default_rules}[/green]")

    # 2.5: Create Claude Hooks (Verified Pattern)
    claude_dir = project_root / ".claude"
    claude_dir.mkdir(exist_ok=True)
    settings_path = claude_dir / "settings.json"

    if not settings_path.exists():
        hooks_config = {
            "hooks": {
                "SessionStart": [
                    {
                        "matcher": "startup",
                        "hooks": [
                            {
                                "type": "command",
                                "command": "cat $CLAUDE_PROJECT_DIR/.warden/AI_RULES.md"
                            }
                        ]
                    }
                ]
            }
        }
        with open(settings_path, "w") as f:
            json.dump(hooks_config, f, indent=2)
        console.print(f"[green]✓ Created Claude Hooks: {settings_path}[/green]")

    # 3. Configure MCP (Global Configs)
    import sys

    # Path to warden executable
    # Priority 1: Current Python Environment's Warden (venv)
    # This ensures we use the version installed in this environment
    venv_warden = Path(sys.prefix) / "bin" / "warden"

    warden_abs = None
    if venv_warden.exists():
         warden_abs = str(venv_warden)
    else:
        # Priority 2: System Path (Resolve to absolute)
        # shutil.which returns absolute path if found
        which_warden = shutil.which("warden")
        if which_warden:
            warden_abs = which_warden
        else:
             # Priority 3: Common Homebrew/Local locations
             # GUI apps often don't have user PATH, so we must be explicit
             common_paths = [
                 Path("/opt/homebrew/bin/warden"),
                 Path("/usr/local/bin/warden"),
                 Path.home() / ".local/bin/warden"
             ]
             for p in common_paths:
                 if p.exists():
                     warden_abs = str(p)
                     break

    # Fallback (User must verify PATH)
    if not warden_abs:
        warden_abs = "warden"
        console.print("[yellow]Warning: Could not resolve absolute path for 'warden'. utilizing relative path.[/yellow]")

    mcp_config_entry = {
        "command": warden_abs,
        "args": ["serve", "mcp"],
        "env": {
             "ProjectRoot": str(project_root.resolve())
        }
    }

    configs_to_update = [
        Path.home() / ".cursor" / "mcp.json",
        Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json",
        Path.home() / ".config" / "claude-code" / "mcp_settings.json", # Claude Code CLI
        Path.home() / ".gemini" / "antigravity" / "mcp_config.json", # Antigravity Support
    ]

    for cfg_path in configs_to_update:
        if cfg_path.exists():
            try:
                with open(cfg_path) as f:
                    content = f.read().strip()
                    if not content:
                        data = {}
                    else:
                        data = json.loads(content)

                if "mcpServers" not in data:
                    data["mcpServers"] = {}

                # Check if warden exists or needs update
                data["mcpServers"].get("warden")

                # Update if missing or root is different (simple overwrite strategy for now)
                # Ideally we want to support multiple projects.
                # Standard MCP doesn't support "context-aware" switching easily yet without specific extension support.
                # So we update the 'warden' key to point to THIS project.
                # Warning: This overwrites previous project binding.

                data["mcpServers"]["warden"] = mcp_config_entry

                with open(cfg_path, "w") as f:
                    json.dump(data, f, indent=2)
                console.print(f"[green]✓ Configured MCP in {cfg_path.name}[/green]")

            except Exception as e:
                console.print(f"[red]Failed to update {cfg_path.name}: {e}[/red]")
