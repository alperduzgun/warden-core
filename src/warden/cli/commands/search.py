import typer
from typing import Optional
from rich.console import Console
from rich.table import Table
from warden.services.package_manager.registry import RegistryClient
from warden.shared.infrastructure.logging import get_logger

# Fallback for semantic search (in case deps missing)
try:
    from warden.pipeline.pre_analysis.indexing import CodeIndexer
    from warden.services.semantic_search.service import SemanticSearchService
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
    indexer = CodeIndexer()
    indexer.index_project() # Assumes default path is current dir
    console.print("[bold green]✔[/bold green] Semantic index updated.")

def semantic_search_command(query: str):
    """Search your local codebase semantically."""
    if not SEMANTIC_AVAILABLE:
        console.print("[red]Semantic Search dependencies not installed.[/red]")
        return
        
    console.print(f"Searching for: [bold]{query}[/bold]...")
    service = SemanticSearchService()
    results = service.search(query)
    
    if not results:
        console.print("[yellow]No semantic matches found.[/yellow]")
        return
        
    table = Table(title=f"Semantic Results for '{query}'")
    table.add_column("File", style="cyan")
    table.add_column("Score", justify="right")
    table.add_column("Snippet", style="dim")
    
    for r in results:
        table.add_row(
            r.file_path,
            f"{r.score:.2f}",
            r.content[:100].replace("\n", " ") + "..."
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
    table.add_column("Category", style="green")
    table.add_column("Version", style="magenta")
    table.add_column("Stats", justify="right")
    table.add_column("Description", style="dim")

    for f in results:
        stats = f"⭐ {f['stars']} | ⬇️ {f['downloads']}"
        table.add_row(
            f["id"],
            f["name"],
            f["category"],
            f["version"],
            stats,
            f["description"]
        )

    console.print(table)
    console.print(f"\n[dim]Use [bold white]warden install <id>[/bold white] to add a frame to your project.[/dim]")
