"""Indexed agent and project metadata for Spotlight navigation."""

from alembic import op

from cognis.store.palette_indexes import (
    drop_palette_destination_indexes,
    ensure_palette_destination_indexes,
)

revision = "170_palette_destinations"
down_revision = "169_palette_latest_task_run"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            ensure_palette_destination_indexes(op.get_bind(), concurrently=True)
    else:
        ensure_palette_destination_indexes(op.get_bind())


def downgrade() -> None:
    drop_palette_destination_indexes(op.get_bind())
