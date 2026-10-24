"""Personal artifact and deliverable lineage bookmarks."""

import sqlalchemy as sa
from alembic import op

revision = "166_document_favorites"
down_revision = "165_executor_recovery_notices"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("document_favorites"):
        return
    op.create_table(
        "document_favorites",
        sa.Column("user_email", sa.String(), primary_key=True),
        sa.Column("kind", sa.String(), primary_key=True),
        sa.Column("lineage_id", sa.String(), primary_key=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("document_favorites")
