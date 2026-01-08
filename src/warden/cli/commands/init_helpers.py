"""
Initialization Helpers for Warden CLI.
Handles interactive configuration prompts.
"""

import os
from pathlib import Path
from rich.console import Console
from rich.prompt import Prompt, Confirm

console = Console()

def configure_llm(existing_config: dict) -> tuple[dict, dict]:
    """Configure LLM settings interactively."""
    console.print("\n[bold cyan]🧠 AI & LLM Configuration[/bold cyan]")
    llm_cfg = existing_config.get('llm', {})
    existing_provider = llm_cfg.get('provider', 'openai')
    existing_model = llm_cfg.get('model', 'gpt-4o')
    env_vars = {}
    
    provider_choices = ["openai", "azure", "groq", "anthropic", "none (static only)"]
    default_prov = existing_provider if existing_provider in provider_choices else "openai"
    provider_selection = Prompt.ask("Select LLM Provider", choices=provider_choices, default=default_prov)
    
    if provider_selection == "none (static only)":
        if not Confirm.ask("Proceed without AI?", default=False):
            return configure_llm(existing_config)
        return {"provider": "none", "model": "none"}, {}

    provider = provider_selection
    model = Prompt.ask("Select Model", default=existing_model)
    key_var = f"{provider.upper()}_API_KEY"
    
    if provider == "azure":
        env_vars["AZURE_OPENAI_API_KEY"] = Prompt.ask("Azure API Key", password=True)
        env_vars["AZURE_OPENAI_ENDPOINT"] = Prompt.ask("Azure Endpoint")
        env_vars["AZURE_OPENAI_DEPLOYMENT_NAME"] = Prompt.ask("Deployment Name")
    else:
        has_key = key_var in os.environ or any(k.endswith("_API_KEY") for k in existing_config.get('llm', {}))
        if not has_key:
             env_vars[key_var] = Prompt.ask(f"{provider} API Key", password=True)

    llm_config = {"provider": provider, "model": model, "timeout": 300}
    if provider == "azure":
        llm_config['azure'] = {
            "endpoint": "${AZURE_OPENAI_ENDPOINT}",
            "api_key": "${AZURE_OPENAI_API_KEY}",
            "deployment_name": "${AZURE_OPENAI_DEPLOYMENT_NAME}",
            "api_version": "2024-02-15-preview"
        }
    return llm_config, env_vars

def configure_vector_db() -> dict:
    """Configure Vector Database settings interactively."""
    console.print("\n[bold cyan]🗄️  Vector Database Configuration[/bold cyan]")
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

    # 3. Configure MCP (Global Configs)
    import json
    
    # Path to warden executable
    import sys
    import shutil
    
    # Priority 1: Current Python Environment's Warden (venv)
    # This ensures we use the version installed in this environment (likely the Python Core version)
    # rather than a global Node.js version causing conflicts.
    venv_warden = Path(sys.prefix) / "bin" / "warden"
    if venv_warden.exists():
        warden_abs = str(venv_warden)
    else:
        # Priority 2: System Path
        warden_abs = shutil.which("warden") or "warden"
    
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
                current_config = data["mcpServers"].get("warden")
                
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

