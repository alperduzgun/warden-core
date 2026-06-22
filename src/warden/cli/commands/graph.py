"""
Symbol graph commands.

  warden graph build [--force]   — enumerate the whole project, build the
                                   symbol graph and persist it to the durable
                                   GraphStore DB (.warden/graph.db).
  warden graph status            — show head / counts / languages / size /
                                   staleness for the persisted graph DB.

The graph is built from the *full* project (Rust discovery path), not the
narrower scan scope, so downstream phases can read whole-project structure
even when a scan only parses changed files.
"""

from __future__ import annotations

import asyncio
import time
from collections import Counter
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from warden.analysis.services.code_graph_builder import CodeGraphBuilder
from warden.analysis.services.graph_store_factory import default_db_path, get_graph_store

graph_app = typer.Typer(name="graph", help="Build and inspect the project symbol graph", no_args_is_help=True)
console = Console()

# Languages the CodeGraphBuilder actually models (K3: Python-first).
# Discovery still enumerates the whole project; only these get parsed.
_GRAPH_LANGUAGES = ("python",)


async def _discover_and_parse(project_root: Path) -> tuple[dict, dict[str, str], int]:
    """Discover every project file (Rust path) and parse the graph languages.

    Returns ``(ast_cache, content_hashes, sources, total_discovered)`` where the
    cache and sources are keyed by absolute path and hashes by relative path.
    ``sources`` feeds deterministic docstring extraction (#690).
    """
    from warden.analysis.application.discovery.discoverer import FileDiscoverer
    from warden.ast.application.provider_registry import ASTProviderRegistry
    from warden.ast.domain.enums import CodeLanguage
    from warden.shared.utils.language_utils import get_language_from_path

    discoverer = FileDiscoverer(root_path=project_root, use_gitignore=True)
    result = await discoverer.discover_async()
    discovered = result.files
    total_discovered = len(discovered)

    registry = ASTProviderRegistry()
    await registry.discover_providers()

    ast_cache: dict = {}
    content_hashes: dict[str, str] = {}
    sources: dict[str, str] = {}

    for dfile in discovered:
        path = Path(dfile.path)
        try:
            language = get_language_from_path(path)
        except Exception:
            continue
        if language is None or language.value not in _GRAPH_LANGUAGES:
            continue

        provider = registry.get_provider(language)
        if provider is None:
            continue

        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if not content.strip():
            continue

        if hasattr(provider, "ensure_grammar"):
            try:
                await provider.ensure_grammar(language)
            except Exception:
                pass

        try:
            ast_cache[str(path)] = await provider.parse(content, language, str(path))
        except Exception:
            continue

        sources[str(path)] = content
        rel = dfile.relative_path or str(path)
        if dfile.hash:
            content_hashes[rel] = dfile.hash

    return ast_cache, content_hashes, sources, total_discovered


@graph_app.command(name="build")
def build_command(
    project_path: Path = typer.Argument(
        Path("."),
        help="Project root to scan [default: current directory]",
        show_default=True,
    ),
    force: bool = typer.Option(
        False, "--force", help="Rebuild from scratch (delete the existing graph DB first)"
    ),
) -> None:
    """Build the whole-project symbol graph and persist it to the GraphStore DB."""
    project_root = project_path.resolve()
    db_path = default_db_path(project_root)

    if force and db_path.exists():
        # WAL/SHM side files must go too so the rebuild starts clean.
        for suffix in ("", "-wal", "-shm"):
            sidecar = Path(str(db_path) + suffix)
            if sidecar.exists():
                sidecar.unlink()
        console.print(f"[yellow]Removed existing graph DB ({db_path.name}) for --force rebuild[/yellow]")

    db_path.parent.mkdir(parents=True, exist_ok=True)

    start = time.perf_counter()
    ast_cache, content_hashes, sources, total_discovered = asyncio.run(_discover_and_parse(project_root))

    builder = CodeGraphBuilder(ast_cache, project_root=project_root)
    store = get_graph_store("sqlite", path=str(db_path))
    try:
        # build_into_store enforces: extract → resolve → fan-in → classify.
        graph = builder.build_into_store(
            store, content_hashes=content_hashes, populate_intent=True, sources=sources
        )
        status = store.status()
        intent = store.intent_stats()
    finally:
        store.close()

    duration = time.perf_counter() - start
    stats = graph.stats()

    console.print("[bold green]Graph build complete[/bold green]")
    console.print(f"  DB:           {db_path}")
    console.print(f"  Files seen:   {total_discovered} (parsed: {len(ast_cache)})")
    console.print(f"  Nodes:        {status['node_count']}")
    console.print(f"  Edges:        {status['edge_count']}")
    console.print(f"  Classes:      {stats['classes']}   Functions: {stats['functions']}")
    console.print(
        f"  Roles:        {intent['symbols_with_role']}/{intent['total_symbols']} "
        f"({intent['role_coverage']:.1%})   public_api: {intent['public_api']}"
    )
    console.print(f"  Duration:     {duration:.2f}s")


@graph_app.command(name="status")
def status_command(
    project_path: Path = typer.Argument(
        Path("."),
        help="Project root [default: current directory]",
        show_default=True,
    ),
) -> None:
    """Show head / counts / languages / size / staleness for the graph DB."""
    project_root = project_path.resolve()
    db_path = default_db_path(project_root)

    if not db_path.exists():
        console.print(f"[yellow]No graph DB found at {db_path}[/yellow]")
        console.print("Run [bold]warden graph build[/bold] to create it.")
        raise typer.Exit(code=1)

    store = get_graph_store("sqlite", path=str(db_path))
    try:
        status = store.status()
        export = store.export_json()
        intent = store.intent_stats()
    finally:
        store.close()

    # Language distribution from the persisted node file paths.
    lang_counter: Counter[str] = Counter()
    for node in export.get("nodes", []):
        suffix = Path(node.get("file_path", "")).suffix.lstrip(".") or "other"
        lang_counter[suffix] += 1

    size_bytes = db_path.stat().st_size
    db_mtime = db_path.stat().st_mtime

    # Staleness: any source file newer than the DB means the graph is stale.
    stale, newer_count = _compute_staleness(project_root, db_mtime)

    table = Table(title="Warden Symbol Graph", show_header=False, box=None)
    table.add_row("DB path", str(db_path))
    table.add_row("Backend", str(status.get("backend")))
    table.add_row("Schema version", str(status.get("schema_version")))
    table.add_row("Nodes", str(status.get("node_count")))
    table.add_row("Edges", str(status.get("edge_count")))
    table.add_row("Files", str(status.get("file_count")))
    table.add_row("Size", _human_size(size_bytes))
    if lang_counter:
        langs = ", ".join(f"{ext}:{n}" for ext, n in lang_counter.most_common())
        table.add_row("Languages", langs)
    if intent["total_symbols"]:
        table.add_row(
            "Roles (Layer A)",
            f"{intent['symbols_with_role']}/{intent['total_symbols']} "
            f"({intent['role_coverage']:.1%})   public_api: {intent['public_api']}",
        )
        top_roles = ", ".join(f"{r}:{n}" for r, n in list(intent["role_distribution"].items())[:6])
        if top_roles:
            table.add_row("Top roles", top_roles)
    table.add_row("Staleness", "[red]STALE[/red]" if stale else "[green]fresh[/green]")
    if stale:
        table.add_row("Files newer than DB", str(newer_count))
    console.print(table)


def _compute_staleness(project_root: Path, db_mtime: float) -> tuple[bool, int]:
    """Return ``(is_stale, files_newer_than_db)`` via a fast Rust discovery."""
    from warden.analysis.application.discovery.discoverer import FileDiscoverer

    try:
        discoverer = FileDiscoverer(root_path=project_root, use_gitignore=True)
        result = discoverer.discover_sync()
    except Exception:
        return False, 0

    newer = 0
    for dfile in result.files:
        try:
            if Path(dfile.path).stat().st_mtime > db_mtime:
                newer += 1
        except OSError:
            continue
    return newer > 0, newer


def _human_size(size_bytes: int) -> str:
    """Format a byte count as a short human-readable string."""
    value = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"
