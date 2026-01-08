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
