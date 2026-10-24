"""Indexed latest scheduled task execution lookup for Spotlight."""

from alembic import op

from cognis.store.palette_indexes import ensure_palette_task_run_index

revision = "169_palette_latest_task_run"
down_revision = "168_palette_name_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            ensure_palette_task_run_index(op.get_bind(), concurrently=True)
    else:
        ensure_palette_task_run_index(op.get_bind())


def downgrade() -> None:
    op.drop_index("ix_tasks_palette_latest_run", table_name="tasks", if_exists=True)
