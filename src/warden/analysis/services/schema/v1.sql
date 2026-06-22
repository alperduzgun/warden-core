-- SqliteGraphStore schema — version 1 (#686)
--
-- Symbol-level dependency graph persistence backing the GraphStore ABC
-- (src/warden/analysis/domain/graph_store.py).
--
-- Design notes:
--   * edges.target_id is NULLable: a CALLS/IMPORTS target may reference an
--     external or not-yet-parsed symbol. When it cannot be resolved to a row
--     in `symbols`, target_fqn_hint preserves the original FQN so who_uses()
--     still works by string match and resolution can be back-filled later.
--   * symbol_intent holds optional "Layer-B" semantic enrichment. Every
--     enrichment column is nullable so Layer-A (pure AST) writes never need it.
--   * graph_fts is an FTS5 virtual table that powers search(). It is populated
--     manually alongside `symbols` (no external-content triggers) so insertion
--     order and partial rebuilds stay predictable.
--   * The whole file is idempotent (IF NOT EXISTS) so it can be applied on
--     every connect without guarding.

-- ── files ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS files (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    path         TEXT    NOT NULL UNIQUE,
    content_hash TEXT    NOT NULL DEFAULT ''
);

-- ── symbols ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS symbols (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    fqn       TEXT    NOT NULL UNIQUE,
    name      TEXT    NOT NULL,
    kind      TEXT    NOT NULL,
    file_id   INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    line      INTEGER NOT NULL DEFAULT 0,
    module    TEXT    NOT NULL DEFAULT '',
    is_test   INTEGER NOT NULL DEFAULT 0,
    bases     TEXT    NOT NULL DEFAULT '[]',   -- JSON array
    metadata  TEXT    NOT NULL DEFAULT '{}'    -- JSON object
);

-- ── edges ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS edges (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id       INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
    target_id       INTEGER          REFERENCES symbols(id) ON DELETE SET NULL,
    target_fqn_hint TEXT,             -- original target FQN (always set)
    relation        TEXT    NOT NULL,
    runtime         INTEGER NOT NULL DEFAULT 1,
    metadata        TEXT    NOT NULL DEFAULT '{}'  -- JSON object
);

-- ── graph_meta (key/value: schema_version, etc.) ─────────────────────
CREATE TABLE IF NOT EXISTS graph_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- ── symbol_intent (semantic enrichment) ─────────────────────────────
--   * Layer-A (#690): deterministic role/summary/centrality/public_api,
--     written during `warden graph build`. source = 'deterministic'.
--   * Layer-B (future): LLM-derived intent/summary/confidence/model.
--   The original Layer-B columns stay nullable so an AST-only write never
--   needs them; the Layer-A columns carry NOT NULL defaults where sensible.
CREATE TABLE IF NOT EXISTS symbol_intent (
    symbol_id  INTEGER PRIMARY KEY REFERENCES symbols(id) ON DELETE CASCADE,
    intent     TEXT,
    summary    TEXT,
    confidence REAL,
    model      TEXT,
    updated_at TEXT,
    -- Layer-A deterministic enrichment (#690)
    role       TEXT,
    centrality INTEGER NOT NULL DEFAULT 0,
    public_api INTEGER NOT NULL DEFAULT 0,
    source     TEXT
);

-- ── full-text search over symbols (FTS5) ─────────────────────────────
-- rowid is kept in lock-step with symbols.id by the store on every write.
CREATE VIRTUAL TABLE IF NOT EXISTS graph_fts USING fts5(
    fqn,
    name,
    module,
    tokenize = 'unicode61'
);

-- ── indexes ──────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_symbols_name_file   ON symbols (name, file_id);
CREATE INDEX IF NOT EXISTS idx_edges_target_rel    ON edges (target_id, relation);
CREATE INDEX IF NOT EXISTS idx_edges_source_rel    ON edges (source_id, relation);
-- supports who_uses() lookups for not-yet-resolved targets
CREATE INDEX IF NOT EXISTS idx_edges_target_hint   ON edges (target_fqn_hint);
-- supports role-based symbol_intent queries (#690)
CREATE INDEX IF NOT EXISTS idx_symbol_intent_role  ON symbol_intent (role);
