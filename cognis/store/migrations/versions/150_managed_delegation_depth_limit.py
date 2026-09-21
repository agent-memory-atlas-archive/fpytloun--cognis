"""Persist managed-conversation delegation depth limits."""

import sqlalchemy as sa
from alembic import op

revision = "150_managed_delegation_depth_limit"
down_revision = "149_signal_destination_policy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("managed_conversation_links")}
    if "depth_limit" not in columns:
        op.add_column(
            "managed_conversation_links",
            sa.Column("depth_limit", sa.Integer(), nullable=False, server_default="1"),
        )
    op.execute(
        sa.text(
            "UPDATE managed_conversation_links "
            "SET depth_limit = COALESCE(("
            "SELECT MAX(descendant.depth) FROM managed_conversation_links AS descendant "
            "WHERE descendant.root_link_id = managed_conversation_links.root_link_id"
            "), depth, 1)"
        )
    )


def downgrade() -> None:
    op.drop_column("managed_conversation_links", "depth_limit")
