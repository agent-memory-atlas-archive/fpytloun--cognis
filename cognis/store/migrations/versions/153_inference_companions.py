"""Add revocable companion inference identities."""

import sqlalchemy as sa
from alembic import op

revision = "153_inference_companions"
down_revision = "152_provider_monitor"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "inference_companions" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "inference_companions",
        sa.Column("service", sa.String(), primary_key=True),
        sa.Column("token_version", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("embedding_reference", sa.String(), nullable=True),
        sa.Column("embedding_dimensions", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("inference_companions")
