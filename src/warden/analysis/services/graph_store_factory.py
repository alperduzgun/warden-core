"""
GraphStore backend factory.

Resolves the persistence backend from configuration.
Currently only ``sqlite`` is supported; ``kuzu`` is reserved for future use.

Usage::

    from warden.analysis.services.graph_store_factory import get_graph_store

    store = get_graph_store()            # default (sqlite when #686 lands)
    store = get_graph_store("memory")    # in-memory double (tests)
    store = get_graph_store("sqlite")    # placeholder — raises until #686
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

from warden.analysis.domain.graph_store import GraphStore

logger = logging.getLogger(__name__)

# Type alias for supported backend names.
BackendName = Literal["memory", "sqlite", "kuzu"]

# Default on-disk location for the persistent symbol graph, relative to a
# project root.  Shared by `warden graph` and the PreAnalysis read path so
# both agree on where the durable DB lives.
DEFAULT_DB_RELPATH = ".warden/graph.db"


def default_db_path(project_root: str | Path) -> Path:
    """Return the canonical persistent graph DB path for a project."""
    return Path(project_root) / DEFAULT_DB_RELPATH


# Registry of known backends.  Populated lazily on first request.
_REGISTRY: dict[str, type[GraphStore]] = {}


def register_backend(name: str, cls: type[GraphStore]) -> None:
    """Register a GraphStore implementation under *name*.

    Called automatically by backend modules on import.
    """
    _REGISTRY[name] = cls
    logger.debug("graph_store_backend_registered", extra={"backend": name})


def get_graph_store(backend: str = "memory", **kwargs: object) -> GraphStore:
    """Instantiate and return a :class:`GraphStore` for the given *backend*.

    Args:
        backend: One of ``"memory"``, ``"sqlite"``, ``"kuzu"``.
        **kwargs: Forwarded to the backend constructor.

    Returns:
        A ready-to-use GraphStore instance.

    Raises:
        ValueError: If the backend name is unknown.
        NotImplementedError: If the backend is reserved but not yet implemented.
    """
    # Lazy-import built-in backends so they self-register.
    _ensure_builtin_backends()

    if backend not in _REGISTRY:
        known = ", ".join(sorted(_REGISTRY)) or "(none)"
        raise ValueError(f"Unknown graph store backend '{backend}'. Known: {known}")

    cls = _REGISTRY[backend]
    logger.info("graph_store_created", extra={"backend": backend})
    return cls(**kwargs)


def _ensure_builtin_backends() -> None:
    """Import built-in backends so they register themselves."""
    if "memory" not in _REGISTRY:
        from warden.analysis.services.memory_graph_store import MemoryGraphStore

    # SQLite backend (#686) — self-registers on import.
    if "sqlite" not in _REGISTRY:
        from warden.analysis.services.sqlite_graph_store import SqliteGraphStore

    if "kuzu" not in _REGISTRY:

        class _KuzuPlaceholder(GraphStore):
            """Reserved slot for Kuzu graph database backend."""

            def __init__(self, **_: object) -> None:
                raise NotImplementedError(
                    "Kuzu GraphStore backend is reserved for future use. Use backend='memory' for now."
                )

            def upsert_file(self, file_path: str, *, content_hash: str = "") -> None: ...
            def upsert_symbols(self, symbols: list) -> None: ...
            def upsert_edges(self, edges: list) -> None: ...
            def delete_file(self, file_path: str) -> None: ...
            def who_uses(self, symbol_fqn: str, *, include_tests: bool = False) -> list: ...
            def callers(self, symbol_fqn: str) -> list: ...
            def callees(self, symbol_fqn: str) -> list: ...
            def impact(self, target_fqn: str, *, max_depth: int = 5) -> list: ...
            def reverse_impact(self, fqn: str, *, max_depth: int = 5, include_tests: bool = False) -> list: ...
            def find_orphan_symbols(self) -> list: ...
            def find_circular_deps(self) -> list: ...
            def get_node(self, fqn: str) -> object | None: ...
            def who_inherits(self, fqn: str) -> list: ...
            def who_implements(self, fqn: str) -> list: ...
            def edges_from(self, fqn: str, *, relation: object | None = None) -> list: ...
            def search(self, query: str, *, kind: str | None = None, limit: int = 50) -> list: ...
            def status(self) -> dict: ...
            def export_json(self) -> dict: ...
            def close(self) -> None: ...

        register_backend("kuzu", _KuzuPlaceholder)
