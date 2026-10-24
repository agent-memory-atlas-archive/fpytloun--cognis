"""Agent hook definitions, assignments, dispatch metadata and turn ordinals."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "162_agent_hooks"
down_revision = "161_inference_routes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Bootstrap creates these new tables through Base.metadata.create_all."""
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for name, create in (
        ("agent_hooks", _create_hooks),
        ("agent_hook_assignments", _create_assignments),
        ("agent_hook_turns", _create_turns),
        ("agent_hook_runs", _create_runs),
    ):
        if name not in tables:
            create()


def _create_hooks() -> None:
    op.create_table(
        "agent_hooks",
        sa.Column("hook_id", sa.String(), primary_key=True),
        sa.Column("owner_email", sa.String(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("definition", sa.JSON(), nullable=False),
    )
    op.create_index("ix_agent_hooks_owner_email", "agent_hooks", ["owner_email"])


def _create_assignments() -> None:
    op.create_table(
        "agent_hook_assignments",
        sa.Column(
            "agent_id",
            sa.String(),
            sa.ForeignKey("agents.agent_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("hook_id", sa.String(), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
    )


def _create_turns() -> None:
    op.create_table(
        "agent_hook_turns",
        sa.Column("conversation_id", sa.String(), primary_key=True),
        sa.Column("turn_id", sa.String(), primary_key=True),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.UniqueConstraint("conversation_id", "ordinal", name="uq_hook_turn_ordinal"),
    )


def _create_runs() -> None:
    op.create_table(
        "agent_hook_runs",
        sa.Column("run_id", sa.String(), primary_key=True),
        sa.Column("hook_id", sa.String(), nullable=False),
        sa.Column("hook_revision", sa.Integer(), nullable=False),
        sa.Column("owner_email", sa.String(), nullable=False),
        sa.Column("agent_id", sa.String(), nullable=False),
        sa.Column("conversation_id", sa.String(), nullable=False),
        sa.Column("source_session_id", sa.String(), nullable=False),
        sa.Column("occurrence", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("lifecycle_pending", sa.Boolean(), nullable=False),
        sa.Column("child_conversation_id", sa.String(), nullable=True),
        sa.Column("task_id", sa.String(), nullable=True),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "hook_id", "conversation_id", "occurrence", name="uq_hook_run_occurrence"
        ),
    )
    op.create_index("ix_agent_hook_runs_owner_email", "agent_hook_runs", ["owner_email"])
    op.create_index("ix_hook_runs_status", "agent_hook_runs", ["status", "created_at"])


def downgrade() -> None:
    """Remove hook metadata without modifying conversation histories."""
    for table in ("agent_hook_runs", "agent_hook_turns", "agent_hook_assignments", "agent_hooks"):
        op.drop_table(table)
