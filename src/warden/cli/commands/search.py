import typer
from typing import Optional
from rich.console import Console
from rich.table import Table
from warden.services.package_manager.registry import RegistryClient
from warden.shared.infrastructure.logging import get_logger

# Fallback for semantic search (in case deps missing)
# Semantic Search Imports
try:
    from warden.semantic_search.indexer import CodeIndexer
    from warden.shared.services.semantic_search_service import SemanticSearchService
    SEMANTIC_AVAILABLE = True
except ImportError:
    SEMANTIC_AVAILABLE = False

logger = get_logger(__name__)
console = Console()

# --- Semantic Search Commands ---

def index_command():
    """Build or update the semantic code index."""
    if not SEMANTIC_AVAILABLE:
        console.print("[red]Semantic Search dependencies not installed.[/red]")
        return
        
    console.print("[bold cyan]Warden Indexer[/bold cyan] - Building semantic index...")
    
    # Use the high-level service for proper initialization
    import os
    from pathlib import Path
    
    # Load config manually for standalone command
    import os
    import yaml
    from pathlib import Path
    
    project_root = Path.cwd()
    legacy_config = project_root / ".warden" / "config.yaml"
    config_data = {}
    if legacy_config.exists():
        with open(legacy_config) as f:
            full_config = yaml.safe_load(f)
            config_data = full_config.get("semantic_search", {})
    
    config_data["enabled"] = True
    config_data["project_root"] = str(project_root)

    service = SemanticSearchService(config_data)
    
    if not service.is_available():
         console.print("[red]Error: Semantic Search service not available.[/red]")
         return

    async def _run_index():
        from warden.shared.utils.language_utils import get_code_extensions
        # Discover files to index
        files = []
        for ext in get_code_extensions():
            files.extend(list(project_root.glob(f"**/*{ext}")))
        
        # Filter out venv, node_modules etc.
        files = [f for f in files if not any(p in str(f) for p in ['.venv', 'node_modules', '__pycache__'])]
        
        console.print(f"Indexing {len(files)} files...")
        await service.index_project(project_root, files)

    import asyncio
    asyncio.run(_run_index())
    
    console.print("[bold green]✔[/bold green] Semantic index updated.")

def semantic_search_command(query: str):
    """Search your local codebase semantically."""
    if not SEMANTIC_AVAILABLE:
        console.print("[red]Semantic Search dependencies not installed.[/red]")
        return
        
    console.print(f"Searching for: [bold]{query}[/bold]...")

    async def _run_search():
        from pathlib import Path
        import yaml
        project_root = Path.cwd()
        legacy_config = project_root / ".warden" / "config.yaml"
        config_data = {}
        if legacy_config.exists():
            with open(legacy_config) as f:
                full_config = yaml.safe_load(f)
                config_data = full_config.get("semantic_search", {})
        
        config_data.setdefault("enabled", True)
        config_data["project_root"] = str(project_root)

        service = SemanticSearchService(config_data)
        if not service.is_available():
            console.print("[red]Error: Semantic Search service not available.[/red]")
            return None
            
        return await service.search(query)

    import asyncio
    results = asyncio.run(_run_search())
    
    if results is None:
        return

    if not results:
        console.print("[yellow]No semantic matches found.[/yellow]")
        return
        
    table = Table(title=f"Semantic Results for '{query}'")
    table.add_column("File", style="cyan")
    table.add_column("Score", justify="right")
    table.add_column("Snippet", style="dim")
    
    for r in results:
        table.add_row(
            r.chunk.relative_path,
            f"{r.score:.2f}",
            r.chunk.content[:100].replace("\n", " ") + "..."
        )
    console.print(table)

# --- Hub Search (The new functionality) ---

def search_command(
    query: Optional[str] = typer.Argument(None, help="Search query"),
    local: bool = typer.Option(False, "--local", "-l", help="Search the local codebase semantically instead of the Hub")
):
    """
    Search for frames in the Warden Hub or search local codebase semantically.
    """
    if local:
        if not query:
            console.print("[red]Error: Query required for local semantic search.[/red]")
            return
        semantic_search_command(query)
        return

    client = RegistryClient()
    results = client.search(query)

    if not results:
        console.print(f"[yellow]No frames found matching '[bold]{query}[/bold]'[/yellow]")
        return

    table = Table(title="Warden Hub - Available Frames", show_lines=True)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Name", style="bold white")
    table.add_column("Tier", justify="center")
    table.add_column("Category", style="green")
    table.add_column("Version", style="magenta")
    table.add_column("Description", style="dim")

    for f in results:
        tier = f.get("tier", "optional").upper()
        tier_style = "bold green" if tier == "CORE" else "blue"
        
        table.add_row(
            f["id"],
            f["name"],
            f"[{tier_style}]{tier}[/{tier_style}]",
            f.get("category", "N/A"),
            f.get("version", "1.0.0"),
            f.get("description", "")
        )

    console.print(table)
    console.print(f"\n[dim]Use [bold white]warden install <id>[/bold white] to add a frame to your project.[/dim]")
