"""Postgres connection and forward-only migration runner (milestone 5a).

CLAUDE.md: "Migrations: forward-only." There is no down-migration path
here and none should be added -- a mistake is fixed with a new forward
migration, not by rewriting history.
"""

from __future__ import annotations

from pathlib import Path

import psycopg

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def connect(dsn: str, connect_timeout: int | None = None) -> psycopg.Connection:
    """Thin wrapper over psycopg.connect().

    Callers that need a fast, loud failure against an unreachable host
    (e.g. gate-5a's own connectivity check) must pass connect_timeout
    explicitly -- confirmed directly that a stopped container on
    Docker Desktop for Windows doesn't refuse a connection promptly, so
    the OS-level default timeout can otherwise leave a caller hanging for
    tens of seconds rather than failing fast.
    """
    if connect_timeout is not None:
        return psycopg.connect(dsn, connect_timeout=connect_timeout)
    return psycopg.connect(dsn)


def apply_migrations(conn: psycopg.Connection) -> list[str]:
    """Apply any not-yet-applied migration under migrations/, in filename order.

    Returns the names of migrations actually applied by this call (empty
    if the schema was already current).
    """
    with conn.cursor() as cur:
        cur.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(name TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("SELECT name FROM schema_migrations")
        applied = {row[0] for row in cur.fetchall()}

    newly_applied: list[str] = []
    for migration_path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if migration_path.name in applied:
            continue
        with conn.cursor() as cur:
            cur.execute(migration_path.read_text(encoding="utf-8"))
            cur.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (migration_path.name,))
        conn.commit()
        newly_applied.append(migration_path.name)
    return newly_applied
