"""Add deliverable revision lineage columns."""

import sqlalchemy as sa
from alembic import op

revision = "154_deliverable_revisions"
down_revision = "153_inference_companions"
branch_labels = None
depends_on = None

_LIVE_SUPERSEDES_PREDICATE = (
    "supersedes_deliverable_id IS NOT NULL AND status IN ('buffered', 'approved', 'delivered')"
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("deliverables")}
    if "lineage_id" not in columns:
        op.add_column("deliverables", sa.Column("lineage_id", sa.String(), nullable=True))
    if "revision" not in columns:
        op.add_column(
            "deliverables",
            sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        )
    if "supersedes_deliverable_id" not in columns:
        op.add_column(
            "deliverables",
            sa.Column("supersedes_deliverable_id", sa.String(), nullable=True),
        )
    op.execute(
        sa.text("UPDATE deliverables SET lineage_id = deliverable_id WHERE lineage_id IS NULL")
    )
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("deliverables")}
    if "ix_deliverables_lineage" not in indexes:
        op.create_index("ix_deliverables_lineage", "deliverables", ["lineage_id", "revision"])
    if "uq_deliverables_live_supersedes" not in indexes:
        op.create_index(
            "uq_deliverables_live_supersedes",
            "deliverables",
            ["supersedes_deliverable_id"],
            unique=True,
            postgresql_where=sa.text(_LIVE_SUPERSEDES_PREDICATE),
            sqlite_where=sa.text(_LIVE_SUPERSEDES_PREDICATE),
        )


def downgrade() -> None:
    op.drop_index("uq_deliverables_live_supersedes", table_name="deliverables")
    op.drop_index("ix_deliverables_lineage", table_name="deliverables")
    with op.batch_alter_table("deliverables") as batch:
        batch.drop_column("supersedes_deliverable_id")
        batch.drop_column("revision")
        batch.drop_column("lineage_id")
