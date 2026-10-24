"""Native metadata name indexes for the command palette."""

from alembic import op

from cognis.store.palette_indexes import drop_palette_indexes, ensure_palette_indexes

revision = "168_palette_name_indexes"
down_revision = "167_video_provider_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            ensure_palette_indexes(op.get_bind(), concurrently=True)
    else:
        ensure_palette_indexes(op.get_bind())


def downgrade() -> None:
    drop_palette_indexes(op.get_bind())
