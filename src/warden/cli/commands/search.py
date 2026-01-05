"""
Warden Search CLI Command.

Provides semantic code search functionality.
"""

import asyncio
import typer
from pathlib import Path
from typing import Optional
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()


def search_command(
    query: str = typer.Argument(..., help="Search query (natural language or code pattern)"),
    limit: int = typer.Option(5, "--limit", "-l", help="Maximum number of results"),
    language: Optional[str] = typer.Option(None, "--language", "-L", help="Filter by language"),
    min_score: float = typer.Option(0.5, "--min-score", "-s", help="Minimum similarity score (0.0-1.0)"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed output"),
):
    """
    Search codebase using semantic similarity.

    Examples:
        warden search "database connection handling"
        warden search "authentication logic" --limit 10
        warden search "SQL query" --language python
    """
    asyncio.run(_search_async(query, limit, language, min_score, verbose))


async def _search_async(query: str, limit: int, language: Optional[str], min_score: float, verbose: bool):
    """Async search implementation."""
    import yaml
    
    console.print(f"[bold cyan]🔍 Semantic Search[/bold cyan]")
    console.print(f"[dim]Query: {query}[/dim]\n")

    # Load config
    config_path = Path.cwd() / ".warden" / "config.yaml"
    if not config_path.exists():
        console.print("[red]Error: .warden/config.yaml not found. Run 'warden init' first.[/red]")
        raise typer.Exit(1)

    with open(config_path) as f:
        config = yaml.safe_load(f)

    ss_config = config.get("semantic_search", {})
    if not ss_config.get("enabled"):
        console.print("[yellow]⚠️  Semantic search is disabled in config.[/yellow]")
        console.print("[dim]Enable it in .warden/config.yaml under semantic_search.enabled[/dim]")
        raise typer.Exit(1)

    # Initialize service
    try:
        from warden.shared.services.semantic_search_service import SemanticSearchService
        
        # Reset singleton for fresh config
        SemanticSearchService._instance = None
        service = SemanticSearchService(ss_config)
        
        if not service.is_available():
            console.print("[red]Error: Semantic search service not available.[/red]")
            raise typer.Exit(1)

        # Check index status
        stats = service.indexer.get_stats()
        if stats.total_chunks == 0:
            console.print("[yellow]⚠️  Index is empty. Run 'warden index' or 'warden scan' first.[/yellow]")
            raise typer.Exit(1)

        if verbose:
            console.print(f"[dim]Index stats: {stats.total_chunks} chunks[/dim]")

        # Execute search
        results = await service.search(
            query=query,
            limit=limit,
            language=language
        )

        if not results:
            console.print("[yellow]No results found.[/yellow]")
            console.print("[dim]Try a different query or lower the min_score threshold.[/dim]")
            return

        # Display results
        table = Table(title=f"Search Results ({len(results)} found)")
        table.add_column("#", style="dim", width=3)
        table.add_column("Score", style="cyan", width=6)
        table.add_column("File", style="green")
        table.add_column("Lines", style="magenta", width=10)
        table.add_column("Type", style="blue", width=10)

        for i, result in enumerate(results, 1):
            score = f"{result.score:.2f}"
            file_path = result.chunk.relative_path
            lines = f"{result.chunk.start_line}-{result.chunk.end_line}"
            chunk_type = result.chunk.chunk_type.value

            table.add_row(str(i), score, file_path, lines, chunk_type)

        console.print(table)

        # Show snippets in verbose mode
        if verbose:
            console.print("\n[bold]Code Snippets:[/bold]")
            for i, result in enumerate(results, 1):
                snippet = result.chunk.content[:300]
                if len(result.chunk.content) > 300:
                    snippet += "..."
                console.print(Panel(
                    snippet,
                    title=f"[{i}] {result.chunk.relative_path}:{result.chunk.start_line}",
                    border_style="dim"
                ))

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        if verbose:
            import traceback
            traceback.print_exc()
        raise typer.Exit(1)


def index_command(
    path: str = typer.Argument(".", help="Path to index (file or directory)"),
    force: bool = typer.Option(False, "--force", "-f", help="Force re-index all files"),
    status: bool = typer.Option(False, "--status", "-s", help="Show index status only"),
    clear: bool = typer.Option(False, "--clear", help="Clear the index"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show verbose output"),
):
    """
    Manage the semantic search index.

    Examples:
        warden index               # Index current directory
        warden index src/          # Index specific directory
        warden index --status      # Show index statistics
        warden index --force       # Re-index all files
        warden index --clear       # Clear the index
    """
    asyncio.run(_index_async(path, force, status, clear, verbose))


async def _index_async(path: str, force: bool, status: bool, clear: bool, verbose: bool):
    """Async index implementation."""
    import yaml

    console.print(f"[bold cyan]📚 Semantic Index Manager[/bold cyan]\n")

    # Load config
    config_path = Path.cwd() / ".warden" / "config.yaml"
    if not config_path.exists():
        console.print("[red]Error: .warden/config.yaml not found. Run 'warden init' first.[/red]")
        raise typer.Exit(1)

    with open(config_path) as f:
        config = yaml.safe_load(f)

    ss_config = config.get("semantic_search", {})
    if not ss_config.get("enabled"):
        console.print("[yellow]⚠️  Semantic search is disabled in config.[/yellow]")
        raise typer.Exit(1)

    try:
        from warden.shared.services.semantic_search_service import SemanticSearchService

        # Reset singleton for fresh config
        SemanticSearchService._instance = None
        service = SemanticSearchService(ss_config)

        if not service.is_available():
            console.print("[red]Error: Semantic search service not available.[/red]")
            raise typer.Exit(1)

        # Status only
        if status:
            stats = service.indexer.get_stats()
            console.print(f"[bold]Index Statistics:[/bold]")
            console.print(f"  Total Chunks: [cyan]{stats.total_chunks}[/cyan]")
            console.print(f"  Files Indexed: [cyan]{stats.total_files_indexed}[/cyan]")
            console.print(f"  Languages: [cyan]{list(stats.chunks_by_language.keys())}[/cyan]")
            if stats.last_indexed_at:
                console.print(f"  Last Indexed: [dim]{stats.last_indexed_at}[/dim]")
            return

        # Clear index
        if clear:
            console.print("[yellow]Clearing index...[/yellow]")
            service.indexer.clear()
            console.print("[green]✅ Index cleared.[/green]")
            return

        # Index files
        target_path = Path(path).resolve()
        if not target_path.exists():
            console.print(f"[red]Error: Path not found: {path}[/red]")
            raise typer.Exit(1)

        # Collect files
        code_extensions = {'.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.go', '.rs', '.cpp', '.c', '.h'}
        
        if target_path.is_file():
            files = [target_path]
        else:
            files = [f for f in target_path.rglob("*") if f.is_file() and f.suffix in code_extensions]

        if not files:
            console.print("[yellow]No code files found to index.[/yellow]")
            return

        console.print(f"Found [cyan]{len(files)}[/cyan] files to index...")

        # Index with progress
        with console.status("[bold green]Indexing files...") as spinner:
            result = await service.index_project(Path.cwd(), files, force=force)

        console.print(f"\n[green]✅ Indexing complete![/green]")
        console.print(f"  Chunks indexed: [cyan]{result.total_chunks}[/cyan]")
        console.print(f"  Files processed: [cyan]{result.total_files_indexed}[/cyan]")

        if verbose:
            console.print(f"  Languages: {result.chunks_by_language}")

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        if verbose:
            import traceback
            traceback.print_exc()
        raise typer.Exit(1)
