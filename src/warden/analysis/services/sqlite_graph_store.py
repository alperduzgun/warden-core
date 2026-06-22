"""
SQLite-backed GraphStore implementation (#686).

Durable, single-file persistence for the symbol dependency graph behind the
:class:`~warden.analysis.domain.graph_store.GraphStore` ABC.  Uses WAL journal
mode for concurrent reader/writer access and applies the versioned ``schema/v1.sql``
DDL on connect.

Edges are stored id-first (``source_id``/``target_id``) with a ``target_fqn_hint``
fallback so unresolved or external targets survive without losing query power.
``search`` is powered by the required FTS5 virtual table ``graph_fts``.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

from warden.analysis.domain.code_graph import EdgeRelation, SymbolEdge, SymbolIntent, SymbolKind, SymbolNode
from warden.analysis.domain.graph_store import GraphStore
from warden.analysis.services.graph_store_factory import register_backend

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1"
_SCHEMA_FILE = Path(__file__).parent / "schema" / "v1.sql"
_BUSY_TIMEOUT_MS = 5000

# Column list for reconstructing a SymbolNode; requires `symbols s` joined to
# `files f` so file_path resolves from the FK.
_NODE_COLS = (
    "s.fqn, s.name, s.kind, f.path AS file_path, s.line, "
    "s.module, s.is_test, s.bases, s.metadata"
)


class SqliteGraphStore(GraphStore):
    """GraphStore backed by a single SQLite database file (or ``:memory:``)."""

    def __init__(self, path: str | Path = ":memory:", **_: object) -> None:
        """Open (creating if needed) the SQLite graph database.

        Args:
            path: Filesystem path for the database, or ``":memory:"`` (default)
                for an ephemeral in-memory store.
        """
        self._path = str(path)
        self._closed = False
        self._conn = sqlite3.connect(self._path)
        self._conn.row_factory = sqlite3.Row
        self._configure_connection()
        self._apply_schema()
        self._init_meta()

    # ── connection setup ──────────────────────────────────────────────

    def _configure_connection(self) -> None:
        cur = self._conn.cursor()
        cur.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
        cur.execute("PRAGMA foreign_keys = ON")
        # WAL is a no-op for ":memory:" but harmless; enables concurrent
        # reader/writer access for file-backed databases.
        cur.execute("PRAGMA journal_mode = WAL")
        cur.close()

    def _apply_schema(self) -> None:
        ddl = _SCHEMA_FILE.read_text(encoding="utf-8")
        # executescript commits any pending transaction and runs the DDL as one batch.
        self._conn.executescript(ddl)
        self._migrate_intent_columns()

    def _migrate_intent_columns(self) -> None:
        """Add the Layer-A (#690) symbol_intent columns to pre-existing DBs.

        ``CREATE TABLE IF NOT EXISTS`` never alters an existing table, so a DB
        created before #690 keeps the old column set.  Each column is added
        idempotently (guarded by PRAGMA table_info) so connecting to either a
        fresh or a legacy DB converges on the full schema.
        """
        existing = {
            row["name"]
            for row in self._conn.execute("PRAGMA table_info(symbol_intent)").fetchall()
        }
        additions = (
            ("role", "TEXT"),
            ("centrality", "INTEGER NOT NULL DEFAULT 0"),
            ("public_api", "INTEGER NOT NULL DEFAULT 0"),
            ("source", "TEXT"),
        )
        with self._conn:
            for name, decl in additions:
                if name not in existing:
                    self._conn.execute(f"ALTER TABLE symbol_intent ADD COLUMN {name} {decl}")
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_symbol_intent_role ON symbol_intent (role)"
            )

    def _init_meta(self) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO graph_meta(key, value) VALUES('schema_version', ?) "
                "ON CONFLICT(key) DO NOTHING",
                (SCHEMA_VERSION,),
            )

    # ── write path ────────────────────────────────────────────────────

    def upsert_file(self, file_path: str, *, content_hash: str = "") -> None:
        self._ensure_open()
        with self._conn:
            self._conn.execute(
                "INSERT INTO files(path, content_hash) VALUES(?, ?) "
                "ON CONFLICT(path) DO UPDATE SET content_hash = excluded.content_hash",
                (file_path, content_hash),
            )

    def upsert_symbols(self, symbols: list[SymbolNode]) -> None:
        self._ensure_open()
        with self._conn:
            for sym in symbols:
                file_id = self._ensure_file(sym.file_path)
                self._conn.execute(
                    """
                    INSERT INTO symbols(fqn, name, kind, file_id, line, module, is_test, bases, metadata)
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(fqn) DO UPDATE SET
                        name = excluded.name,
                        kind = excluded.kind,
                        file_id = excluded.file_id,
                        line = excluded.line,
                        module = excluded.module,
                        is_test = excluded.is_test,
                        bases = excluded.bases,
                        metadata = excluded.metadata
                    """,
                    (
                        sym.fqn,
                        sym.name,
                        sym.kind.value,
                        file_id,
                        sym.line,
                        sym.module,
                        1 if sym.is_test else 0,
                        json.dumps(sym.bases),
                        json.dumps(sym.metadata),
                    ),
                )
                self._sync_fts(sym)

    def upsert_edges(self, edges: list[SymbolEdge]) -> None:
        self._ensure_open()
        with self._conn:
            for edge in edges:
                source_id = self._symbol_id(edge.source)
                if source_id is None:
                    # Source must be a known symbol; skip dangling edges rather
                    # than fabricate placeholder symbols (matches build flow,
                    # which always upserts a file's symbols before its edges).
                    logger.warning(
                        "sqlite_graph_store_skip_edge_unknown_source",
                        extra={"source": edge.source, "target": edge.target},
                    )
                    continue
                target_id = self._symbol_id(edge.target)
                self._conn.execute(
                    """
                    INSERT INTO edges(source_id, target_id, target_fqn_hint, relation, runtime, metadata)
                    VALUES(?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source_id,
                        target_id,
                        edge.target,
                        edge.relation.value,
                        1 if edge.runtime else 0,
                        json.dumps(edge.metadata),
                    ),
                )

    def delete_file(self, file_path: str) -> None:
        self._ensure_open()
        with self._conn:
            rows = self._conn.execute(
                "SELECT id FROM symbols WHERE file_id = (SELECT id FROM files WHERE path = ?)",
                (file_path,),
            ).fetchall()
            for row in rows:
                self._conn.execute("DELETE FROM graph_fts WHERE rowid = ?", (row["id"],))
            # ON DELETE CASCADE clears symbols (and their edges/intent) for the file.
            self._conn.execute("DELETE FROM files WHERE path = ?", (file_path,))

    # ── intent / centrality (Layer A, #690) ───────────────────────────

    def compute_fan_in(self) -> dict[str, int]:
        """Aggregate incoming edge counts (centrality) per target via SQL.

        Keys on the resolved target FQN when the edge resolved, else the raw
        ``target_fqn_hint`` (the builder leaves CALLS/INHERITS targets as short
        names).  Returns ``{target_key: fan_in}``; absent keys mean zero.  The
        classifier resolves these keys to symbols by FQN and (graph-unique)
        short name.
        """
        self._ensure_open()
        rows = self._conn.execute(
            """
            SELECT COALESCE(t.fqn, e.target_fqn_hint) AS key, COUNT(*) AS c
            FROM edges e
            LEFT JOIN symbols t ON t.id = e.target_id
            WHERE COALESCE(t.fqn, e.target_fqn_hint) IS NOT NULL
            GROUP BY key
            """
        ).fetchall()
        return {row["key"]: int(row["c"]) for row in rows}

    def upsert_intents(self, intents: list[SymbolIntent]) -> None:
        """Write deterministic Layer-A intent rows, keyed by resolved symbol id.

        Intents whose symbol is unknown (never upserted) are skipped rather
        than fabricating a symbol row.
        """
        self._ensure_open()
        with self._conn:
            for intent in intents:
                symbol_id = self._symbol_id(intent.fqn)
                if symbol_id is None:
                    continue
                self._conn.execute(
                    """
                    INSERT INTO symbol_intent(symbol_id, summary, role, centrality, public_api, source, confidence)
                    VALUES(?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(symbol_id) DO UPDATE SET
                        summary = excluded.summary,
                        role = excluded.role,
                        centrality = excluded.centrality,
                        public_api = excluded.public_api,
                        source = excluded.source,
                        confidence = excluded.confidence
                    """,
                    (
                        symbol_id,
                        intent.summary,
                        intent.role,
                        intent.centrality,
                        1 if intent.public_api else 0,
                        intent.source,
                        intent.confidence,
                    ),
                )

    def intent_stats(self) -> dict[str, Any]:
        """Return Layer-A intent coverage stats for status / acceptance checks.

        Includes total symbols, how many carry a role, the coverage ratio,
        public-API count and the role distribution.
        """
        self._ensure_open()
        total = self._count("symbols")
        with_role = int(
            self._conn.execute(
                "SELECT COUNT(*) AS c FROM symbol_intent WHERE role IS NOT NULL AND role != ''"
            ).fetchone()["c"]
        )
        public = int(
            self._conn.execute(
                "SELECT COUNT(*) AS c FROM symbol_intent WHERE public_api = 1"
            ).fetchone()["c"]
        )
        dist = {
            row["role"]: int(row["c"])
            for row in self._conn.execute(
                "SELECT role, COUNT(*) AS c FROM symbol_intent "
                "WHERE role IS NOT NULL GROUP BY role ORDER BY c DESC"
            ).fetchall()
        }
        return {
            "total_symbols": total,
            "symbols_with_role": with_role,
            "role_coverage": (with_role / total) if total else 0.0,
            "public_api": public,
            "role_distribution": dist,
        }

    def get_intent(self, symbol_fqn: str) -> SymbolIntent | None:
        """Read back a single symbol's Layer-A intent (test / introspection)."""
        self._ensure_open()
        row = self._conn.execute(
            """
            SELECT s.fqn AS fqn, i.role, i.summary, i.centrality, i.public_api, i.source, i.confidence
            FROM symbol_intent i
            JOIN symbols s ON s.id = i.symbol_id
            WHERE s.fqn = ?
            """,
            (symbol_fqn,),
        ).fetchone()
        if row is None or row["role"] is None:
            return None
        return SymbolIntent(
            fqn=row["fqn"],
            role=row["role"],
            summary=row["summary"] or "",
            centrality=int(row["centrality"] or 0),
            public_api=bool(row["public_api"]),
            source=row["source"] or "",
            confidence=float(row["confidence"]) if row["confidence"] is not None else 1.0,
        )

    # ── read path ─────────────────────────────────────────────────────

    def who_uses(self, symbol_fqn: str, *, include_tests: bool = False) -> list[SymbolEdge]:
        self._ensure_open()
        target_id = self._symbol_id(symbol_fqn)
        rows = self._conn.execute(
            """
            SELECT e.relation, e.runtime, e.metadata, e.target_fqn_hint,
                   src.fqn AS source_fqn, src.is_test AS source_is_test,
                   tgt.fqn AS target_fqn
            FROM edges e
            JOIN symbols src ON src.id = e.source_id
            LEFT JOIN symbols tgt ON tgt.id = e.target_id
            WHERE e.target_id = ? OR e.target_fqn_hint = ?
            """,
            (target_id, symbol_fqn),
        ).fetchall()
        results: list[SymbolEdge] = []
        for row in rows:
            if not include_tests and row["source_is_test"]:
                continue
            results.append(self._row_to_edge(row))
        return results

    def callers(self, symbol_fqn: str) -> list[SymbolNode]:
        self._ensure_open()
        target_id = self._symbol_id(symbol_fqn)
        rows = self._conn.execute(
            f"""
            SELECT DISTINCT {_NODE_COLS}
            FROM edges e
            JOIN symbols s ON s.id = e.source_id
            JOIN files f ON f.id = s.file_id
            WHERE e.relation = ? AND (e.target_id = ? OR e.target_fqn_hint = ?)
            """,
            (EdgeRelation.CALLS.value, target_id, symbol_fqn),
        ).fetchall()
        return [self._row_to_node(r) for r in rows]

    def callees(self, symbol_fqn: str) -> list[SymbolNode]:
        self._ensure_open()
        source_id = self._symbol_id(symbol_fqn)
        if source_id is None:
            return []
        rows = self._conn.execute(
            f"""
            SELECT DISTINCT {_NODE_COLS}
            FROM edges e
            JOIN symbols s ON s.id = e.target_id
            JOIN files f ON f.id = s.file_id
            WHERE e.relation = ? AND e.source_id = ?
            """,
            (EdgeRelation.CALLS.value, source_id),
        ).fetchall()
        return [self._row_to_node(r) for r in rows]

    def impact(self, target_fqn: str, *, max_depth: int = 5) -> list[list[SymbolEdge]]:
        self._ensure_open()
        chains: list[list[SymbolEdge]] = []
        queue: list[tuple[str, list[SymbolEdge]]] = [(target_fqn, [])]
        visited: set[str] = set()

        while queue:
            current, path = queue.pop(0)
            if current in visited or len(path) >= max_depth:
                continue
            visited.add(current)

            source_id = self._symbol_id(current)
            if source_id is None:
                continue
            rows = self._conn.execute(
                """
                SELECT e.relation, e.runtime, e.metadata, e.target_fqn_hint,
                       src.fqn AS source_fqn, tgt.fqn AS target_fqn
                FROM edges e
                JOIN symbols src ON src.id = e.source_id
                LEFT JOIN symbols tgt ON tgt.id = e.target_id
                WHERE e.source_id = ?
                """,
                (source_id,),
            ).fetchall()
            for row in rows:
                edge = self._row_to_edge(row)
                new_path = [*path, edge]
                chains.append(new_path)
                queue.append((edge.target, new_path))

        return chains

    def search(self, query: str, *, kind: str | None = None, limit: int = 50) -> list[SymbolNode]:
        self._ensure_open()
        match_expr = _to_fts_query(query)
        if match_expr is None:
            # Empty query → plain scan (FTS5 MATCH cannot match an empty string).
            sql = f"SELECT {_NODE_COLS} FROM symbols s JOIN files f ON f.id = s.file_id"
            params: list[Any] = []
            if kind is not None:
                sql += " WHERE s.kind = ?"
                params.append(kind)
            sql += " LIMIT ?"
            params.append(limit)
            rows = self._conn.execute(sql, params).fetchall()
            return [self._row_to_node(r) for r in rows]

        sql = (
            f"SELECT {_NODE_COLS} FROM graph_fts gf "
            "JOIN symbols s ON s.id = gf.rowid "
            "JOIN files f ON f.id = s.file_id "
            "WHERE graph_fts MATCH ?"
        )
        params = [match_expr]
        if kind is not None:
            sql += " AND s.kind = ?"
            params.append(kind)
        sql += " LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_node(r) for r in rows]

    # ── introspection ─────────────────────────────────────────────────

    def status(self) -> dict[str, Any]:
        if self._closed:
            return {
                "backend": "sqlite",
                "node_count": 0,
                "edge_count": 0,
                "file_count": 0,
                "path": self._path,
                "schema_version": SCHEMA_VERSION,
                "closed": True,
            }
        return {
            "backend": "sqlite",
            "node_count": self._count("symbols"),
            "edge_count": self._count("edges"),
            "file_count": self._count("files"),
            "path": self._path,
            "schema_version": self.schema_version(),
            "closed": False,
        }

    def export_json(self) -> dict[str, Any]:
        self._ensure_open()
        node_rows = self._conn.execute(
            f"SELECT {_NODE_COLS} FROM symbols s JOIN files f ON f.id = s.file_id"
        ).fetchall()
        edge_rows = self._conn.execute(
            """
            SELECT e.relation, e.runtime, e.metadata, e.target_fqn_hint,
                   src.fqn AS source_fqn, tgt.fqn AS target_fqn
            FROM edges e
            JOIN symbols src ON src.id = e.source_id
            LEFT JOIN symbols tgt ON tgt.id = e.target_id
            """
        ).fetchall()
        return {
            "nodes": [self._row_to_node(r).model_dump(mode="json") for r in node_rows],
            "edges": [self._row_to_edge(r).model_dump(mode="json") for r in edge_rows],
        }

    def schema_version(self) -> str:
        """Read the persisted schema version back from ``graph_meta``."""
        row = self._conn.execute(
            "SELECT value FROM graph_meta WHERE key = 'schema_version'"
        ).fetchone()
        return row["value"] if row else ""

    # ── lifecycle ─────────────────────────────────────────────────────

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._conn.close()

    # ── internal helpers ──────────────────────────────────────────────

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("SqliteGraphStore has been closed.")

    def _ensure_file(self, file_path: str) -> int:
        self._conn.execute(
            "INSERT INTO files(path) VALUES(?) ON CONFLICT(path) DO NOTHING",
            (file_path,),
        )
        row = self._conn.execute("SELECT id FROM files WHERE path = ?", (file_path,)).fetchone()
        return int(row["id"])

    def _symbol_id(self, fqn: str) -> int | None:
        row = self._conn.execute("SELECT id FROM symbols WHERE fqn = ?", (fqn,)).fetchone()
        return int(row["id"]) if row else None

    def _sync_fts(self, sym: SymbolNode) -> None:
        sid = self._symbol_id(sym.fqn)
        if sid is None:
            return
        self._conn.execute("DELETE FROM graph_fts WHERE rowid = ?", (sid,))
        self._conn.execute(
            "INSERT INTO graph_fts(rowid, fqn, name, module) VALUES(?, ?, ?, ?)",
            (sid, sym.fqn, sym.name, sym.module),
        )

    def _count(self, table: str) -> int:
        # `table` is never user-controlled (literal call sites only).
        row = self._conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()
        return int(row["c"])

    @staticmethod
    def _row_to_node(row: sqlite3.Row) -> SymbolNode:
        return SymbolNode(
            fqn=row["fqn"],
            name=row["name"],
            kind=SymbolKind(row["kind"]),
            file_path=row["file_path"],
            line=row["line"],
            module=row["module"],
            is_test=bool(row["is_test"]),
            bases=json.loads(row["bases"]),
            metadata=json.loads(row["metadata"]),
        )

    @staticmethod
    def _row_to_edge(row: sqlite3.Row) -> SymbolEdge:
        target = row["target_fqn"] if row["target_fqn"] is not None else row["target_fqn_hint"]
        return SymbolEdge(
            source=row["source_fqn"],
            target=target if target is not None else "",
            relation=EdgeRelation(row["relation"]),
            runtime=bool(row["runtime"]),
            metadata=json.loads(row["metadata"]),
        )


def _to_fts_query(query: str) -> str | None:
    """Turn a free-text query into a safe FTS5 prefix MATCH expression.

    Splits on non-alphanumeric characters and ANDs prefix terms together so
    ``"utils.py"`` becomes ``utils* py*``. Returns ``None`` for empty queries.
    """
    tokens = ["".join(ch for ch in part if ch.isalnum()) for part in query.replace(".", " ").split()]
    terms = [f"{t}*" for t in tokens if t]
    if not terms:
        return None
    return " ".join(terms)


# Self-register so the factory can resolve backend="sqlite".
register_backend("sqlite", SqliteGraphStore)
