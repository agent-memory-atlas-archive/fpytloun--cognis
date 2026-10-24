"""Durable executor recovery notice delivery."""

import sqlalchemy as sa
from alembic import op

revision = "165_executor_recovery_notices"
down_revision = "164_hook_handoff"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("executor_recovery_notices"):
        return  # Startup bootstrap may already have installed the current schema.
    op.create_table(
        "executor_recovery_notices",
        sa.Column("notice_id", sa.String(), primary_key=True),
        sa.Column("conversation_id", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("intaris_session_id", sa.String(), nullable=False),
        sa.Column("user_email", sa.String(), nullable=False),
        sa.Column("agent_id", sa.String(), nullable=False),
        sa.Column("executor_id", sa.String(), nullable=False),
        sa.Column("unavailable_since", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("recovered", sa.Boolean(), nullable=False),
        sa.Column("delivered_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_executor_recovery_notices_pending",
        "executor_recovery_notices",
        ["delivered_at", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("executor_recovery_notices")
