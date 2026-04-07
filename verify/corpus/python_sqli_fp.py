"""
Safe patterns that naive SQL injection scanners wrongly flag.
All of these are parameterized, whitelisted, or otherwise safe.

corpus_labels:
  sql-injection: 0
"""

import asyncpg


# ── asyncpg parameterized queries ────────────────────────────────────────────

async def get_users(pool: asyncpg.Pool, filters: dict) -> list:
    """asyncpg pool.fetch with *params — NOT SQL injection."""
    conditions, params = [], []
    if filters.get("active") is not None:
        conditions.append(f"active = ${len(params) + 1}")
        params.append(filters["active"])
    if filters.get("role"):
        conditions.append(f"role = ${len(params) + 1}")
        params.append(filters["role"])
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    query = f"SELECT * FROM users {where} ORDER BY created_at DESC"
    return await pool.fetch(query, *params)


async def get_server(pool: asyncpg.Pool, server_id: str) -> dict:
    """asyncpg fetchrow with positional param — NOT SQL injection."""
    return await pool.fetchrow(
        "SELECT * FROM servers WHERE id = $1 AND deleted_at IS NULL",
        server_id,
    )


async def count_active(pool: asyncpg.Pool, org_id: str) -> int:
    """asyncpg fetchval — NOT SQL injection."""
    return await pool.fetchval(
        "SELECT COUNT(*) FROM users WHERE org_id = $1 AND active = TRUE",
        org_id,
    )


async def audit_log(pool: asyncpg.Pool, action: str, user_id: str) -> None:
    """asyncpg execute with positional params — NOT SQL injection."""
    await pool.execute(
        "INSERT INTO audit_log (action, user_id, created_at) VALUES ($1, $2, NOW())",
        action,
        user_id,
    )


# ── _SORT_CLAUSES / whitelist mapping ────────────────────────────────────────

_SORT_CLAUSES = {
    "name": "ORDER BY name ASC",
    "created": "ORDER BY created_at DESC",
    "updated": "ORDER BY updated_at DESC",
    "popular": "ORDER BY view_count DESC",
}

_ORDER_BY_MAP = {
    "price_asc": "ORDER BY price ASC",
    "price_desc": "ORDER BY price DESC",
    "rating": "ORDER BY rating DESC NULLS LAST",
}

ALLOWED_COLUMNS = frozenset({"id", "name", "created_at", "updated_at", "status"})


async def get_sorted_items(pool: asyncpg.Pool, sort_key: str) -> list:
    """Whitelist-controlled ORDER BY — NOT SQL injection."""
    order = _SORT_CLAUSES.get(sort_key, "ORDER BY id ASC")
    query = f"SELECT * FROM items {order} LIMIT 100"
    return await pool.fetch(query)


# ── conditions[] + params.append() builder pattern ───────────────────────────

async def search_servers(
    pool: asyncpg.Pool,
    name: str | None = None,
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list:
    """
    Dynamic query builder with params list — NOT SQL injection.
    The WHERE clause uses $N placeholders matched to params list.
    """
    conditions: list[str] = []
    params: list = []

    if name:
        conditions.append(f"name ILIKE ${len(params) + 1}")
        params.append(f"%{name}%")
    if status:
        conditions.append(f"status = ${len(params) + 1}")
        params.append(status)

    params.extend([limit, offset])
    idx = len(params)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    query = (
        f"SELECT * FROM servers {where} "
        f"ORDER BY created_at DESC LIMIT ${idx - 1} OFFSET ${idx}"
    )
    return await pool.fetch(query, *params)


# ── psycopg2 style parameterized ─────────────────────────────────────────────

def get_user_psycopg2(cursor, user_id: int) -> dict:
    """psycopg2 %s placeholder — NOT SQL injection."""
    cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    return cursor.fetchone()


def get_items_psycopg2(cursor, category: str, limit: int) -> list:
    """psycopg2 named params — NOT SQL injection."""
    cursor.execute(
        "SELECT * FROM items WHERE category = %s ORDER BY name LIMIT %s",
        (category, limit),
    )
    return cursor.fetchall()


# ── comment lines mentioning SQL ─────────────────────────────────────────────

# BAD example (do not copy): query = f"SELECT * FROM users WHERE id = {uid}"
# The above is SQL injection — always use parameterized queries instead.

# TODO: migrate this to: cursor.execute("SELECT ... WHERE id = ?", (uid,))


# ── Pattern definitions in security check files ───────────────────────────────

DANGEROUS_SQL_PATTERNS = [
    r"f['\"].*SELECT.*\{",
    r"['\"].*SELECT.*['\"] \+ \w+",
]
SQL_KEYWORDS = ["SELECT", "INSERT", "UPDATE", "DELETE", "DROP", "UNION"]
