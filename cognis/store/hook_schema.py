"""Prospective hook activation upgrade shared by bootstrap and Alembic."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.engine import Connection
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.compiler import SQLCompiler
from sqlalchemy.sql.functions import FunctionElement


class HookActivationTimestamp(FunctionElement[datetime]):
    """Wall-clock activation default shared by fresh and upgraded schemas."""

    type = sa.TIMESTAMP(timezone=True)
    inherit_cache = True


@compiles(HookActivationTimestamp)
def _activation_timestamp(
    element: HookActivationTimestamp, compiler: SQLCompiler, **kw: Any
) -> str:
    return "clock_timestamp()"


@compiles(HookActivationTimestamp, "sqlite")
def _sqlite_activation_timestamp(
    element: HookActivationTimestamp, compiler: SQLCompiler, **kw: Any
) -> str:
    return "STRFTIME('%Y-%m-%d %H:%M:%f', 'now', '+0.001 seconds')"


def ensure_hook_activation_boundary(connection: Connection) -> None:
    """Fence rollout/NULL rows and support inserts from pre-boundary binaries."""
    columns = sa.inspect(connection).get_columns("agent_hook_assignments")
    column = next((column for column in columns if column["name"] == "activated_at"), None)
    if column is None:
        connection.execute(
            sa.text("ALTER TABLE agent_hook_assignments ADD COLUMN activated_at TIMESTAMP")
            if connection.dialect.name == "sqlite"
            else sa.text(
                "ALTER TABLE agent_hook_assignments ADD COLUMN activated_at TIMESTAMP WITH TIME ZONE"
            )
        )
    assignments = sa.table(
        "agent_hook_assignments", sa.column("activated_at", sa.TIMESTAMP(timezone=True))
    )
    connection.execute(
        assignments.update()
        .where(assignments.c.activated_at.is_(None))
        .values(activated_at=datetime.now(UTC))
    )
    # SQLite cannot ALTER a nonconstant default. Rebuild this small configuration
    # table once; round up its millisecond clock so earlier microsecond admissions
    # cannot accidentally cross the server-generated boundary. PostgreSQL uses
    # wall clock, not transaction start, for old binaries' potentially long writes.
    default = str(HookActivationTimestamp().compile(dialect=connection.dialect))
    if (
        column is None
        or str(column.get("default") or "").strip("()").lower() != default.strip("()").lower()
    ):
        operations = Operations(MigrationContext.configure(connection))
        with operations.batch_alter_table("agent_hook_assignments") as batch:
            batch.alter_column(
                "activated_at",
                existing_type=sa.TIMESTAMP(timezone=True),
                server_default=sa.text("(" + default + ")"),
            )


def ensure_hook_handoff(connection: Connection) -> None:
    """Add metadata-only pointers and a cross-controller fork serialization slot."""
    columns = {column["name"] for column in sa.inspect(connection).get_columns("agent_hook_runs")}
    if "handoff" not in columns:
        connection.execute(sa.text("ALTER TABLE agent_hook_runs ADD COLUMN handoff JSON"))
    if "fork_slot" not in columns:
        connection.execute(sa.text("ALTER TABLE agent_hook_runs ADD COLUMN fork_slot VARCHAR"))
    connection.execute(
        sa.text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_hook_fork_slot ON agent_hook_runs (fork_slot)"
        )
    )
    connection.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_hook_child ON agent_hook_runs (child_conversation_id)"
        )
    )
    connection.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_hook_run_scope ON agent_hook_runs "
            "(owner_email, agent_id, hook_id, conversation_id, created_at)"
        )
    )
