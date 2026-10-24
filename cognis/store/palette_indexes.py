"""Native, transactionally maintained name indexes; never index document content."""

from __future__ import annotations

import unicodedata

import sqlalchemy as sa
from sqlalchemy.engine import Connection

# These identifiers are schema constants, never interpolated request input.
CONTENT_SOURCES = (
    ("conversation", "conversations", "conversation_id", "title"),
    ("task", "tasks", "task_id", "title"),
    ("schedule", "schedules", "schedule_id", "name"),
    ("deliverable", "deliverables", "deliverable_id", "title"),
    ("artifact", "artifacts", "artifact_id", "filename"),
)
DESTINATION_SOURCES = (
    ("agent", "agents", "agent_id", "name"),
    ("project", "projects", "project_id", "name"),
)
SOURCES = CONTENT_SOURCES + DESTINATION_SOURCES


def name_expression(kind: str, name: str) -> str:
    """Return a schema-owned expression including both agent identity names."""
    return "coalesce(name, '') || ' ' || coalesce(display_name, '')" if kind == "agent" else name


def _latin_translation() -> tuple[str, str]:
    pairs = []
    for code in (*range(192, 592), *range(7680, 7936)):
        char = chr(code)
        plain = "".join(
            c for c in unicodedata.normalize("NFD", char) if not unicodedata.combining(c)
        )
        if (
            char.islower()
            and len(plain) == 1
            and plain.isascii()
            and plain.isalpha()
            and plain != char
        ):
            pairs.append((char, plain))
    return "".join(char for char, _ in pairs), "".join(plain for _, plain in pairs)


def _ensure_index(
    conn: Connection, name: str, definition: str, *, concurrently: bool = False
) -> None:
    if conn.dialect.name == "postgresql":
        valid = conn.execute(
            sa.text(
                "SELECT i.indisvalid FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid "
                "JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname=current_schema() AND c.relname=:name"
            ),
            {"name": name},
        ).scalar()
        if valid is False:
            conn.execute(sa.text(f"DROP INDEX {'CONCURRENTLY ' if concurrently else ''}{name}"))
    conn.execute(
        sa.text(
            f"CREATE INDEX {'CONCURRENTLY ' if concurrently else ''}IF NOT EXISTS {name} "
            f"{definition}"
        )
    )


def ensure_palette_task_run_index(conn: Connection, *, concurrently: bool = False) -> None:
    """Bound latest scheduled-run probes by owner and stable schedule identity."""
    _ensure_index(
        conn,
        "ix_tasks_palette_latest_run",
        "ON tasks (created_by, source_type, source_ref, created_at, task_id)",
        concurrently=concurrently,
    )


def ensure_palette_indexes(conn: Connection, *, concurrently: bool = False) -> None:
    """Install indexes once, including an idempotent legacy metadata backfill."""
    if conn.dialect.name == "postgresql":
        accented, plain = _latin_translation()
        conn.execute(
            sa.text(
                "CREATE OR REPLACE FUNCTION palette_name_vector(value text) RETURNS tsvector "
                "LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$ "
                "SELECT to_tsvector('simple', regexp_replace("
                f"translate(lower(coalesce(value, '')), '{accented}', '{plain}'), "
                "'[^[:alnum:]]+', ' ', 'g')) $$"
            )
        )
        _ensure_index(
            conn,
            "ix_deliverables_successor_status",
            "ON deliverables (supersedes_deliverable_id, status)",
            concurrently=concurrently,
        )
    _ensure_name_indexes(conn, SOURCES, concurrently=concurrently)


def ensure_palette_destination_indexes(conn: Connection, *, concurrently: bool = False) -> None:
    """Install destination indexes after the original palette name-vector migration."""
    _ensure_name_indexes(conn, DESTINATION_SOURCES, concurrently=concurrently)


def _ensure_name_indexes(
    conn: Connection, sources: tuple[tuple[str, str, str, str], ...], *, concurrently: bool
) -> None:
    if conn.dialect.name == "postgresql":
        for kind, table, _, name in sources:
            _ensure_index(
                conn,
                f"ix_{table}_palette_name",
                f"ON {table} USING gin (palette_name_vector({name_expression(kind, name)}))",
                concurrently=concurrently,
            )
        return
    if conn.dialect.name != "sqlite":
        raise ValueError("Palette indexes require SQLite or PostgreSQL")
    conn.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_deliverables_successor_status "
            "ON deliverables (supersedes_deliverable_id, status)"
        )
    )
    for kind, table, _, name in sources:
        fields = (name, "display_name") if kind == "agent" else (name,)
        columns = ", ".join(fields)
        values = ", ".join(f"coalesce(new.{field}, '')" for field in fields)
        old_values = ", ".join(f"coalesce(old.{field}, '')" for field in fields)
        changed = " OR ".join(f"old.{field} IS NOT new.{field}" for field in fields)
        index = f"palette_{table}"
        exists = conn.execute(
            sa.text("SELECT 1 FROM sqlite_master WHERE name = :name"), {"name": index}
        ).scalar()
        conn.execute(
            sa.text(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS {index} USING fts5("
                f"{columns}, content='{table}', content_rowid='rowid', "
                "tokenize='unicode61 remove_diacritics 2', prefix='2 3 4')"
            )
        )
        conn.execute(
            sa.text(
                f"CREATE TRIGGER IF NOT EXISTS palette_{table}_insert AFTER INSERT ON {table} "
                f"BEGIN INSERT INTO {index}(rowid, {columns}) "
                f"VALUES (new.rowid, {values}); END"
            )
        )
        conn.execute(
            sa.text(
                f"CREATE TRIGGER IF NOT EXISTS palette_{table}_update "
                f"AFTER UPDATE OF {columns} ON {table} WHEN {changed} "
                f"BEGIN INSERT INTO {index}({index}, rowid, {columns}) "
                f"VALUES ('delete', old.rowid, {old_values}); "
                f"INSERT INTO {index}(rowid, {columns}) "
                f"VALUES (new.rowid, {values}); END"
            )
        )
        conn.execute(
            sa.text(
                f"CREATE TRIGGER IF NOT EXISTS palette_{table}_delete AFTER DELETE ON {table} "
                f"BEGIN INSERT INTO {index}({index}, rowid, {columns}) "
                f"VALUES ('delete', old.rowid, {old_values}); END"
            )
        )
        if not exists:
            conn.execute(sa.text(f"INSERT INTO {index}({index}) VALUES ('rebuild')"))


def drop_palette_indexes(conn: Connection) -> None:
    """Remove only palette-owned indexes and triggers."""
    conn.execute(sa.text("DROP INDEX IF EXISTS ix_deliverables_successor_status"))
    _drop_name_indexes(conn, SOURCES)
    if conn.dialect.name == "postgresql":
        conn.execute(sa.text("DROP FUNCTION IF EXISTS palette_name_vector(text)"))


def drop_palette_destination_indexes(conn: Connection) -> None:
    """Remove destination search without touching existing content indexes."""
    _drop_name_indexes(conn, DESTINATION_SOURCES)


def _drop_name_indexes(conn: Connection, sources: tuple[tuple[str, str, str, str], ...]) -> None:
    for _, table, _, _ in sources:
        if conn.dialect.name == "postgresql":
            conn.execute(sa.text(f"DROP INDEX IF EXISTS ix_{table}_palette_name"))
        else:
            for operation in ("insert", "update", "delete"):
                conn.execute(sa.text(f"DROP TRIGGER IF EXISTS palette_{table}_{operation}"))
            conn.execute(sa.text(f"DROP TABLE IF EXISTS palette_{table}"))
