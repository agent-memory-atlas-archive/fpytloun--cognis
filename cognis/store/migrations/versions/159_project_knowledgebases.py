"""Add project knowledgebase assignments."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "159_project_knowledgebases"
down_revision = "158_merge_artifact_workflow"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create assignments; startup bootstrap creates this new table via metadata."""
    if sa.inspect(op.get_bind()).has_table("project_knowledgebases"):
        return
    op.create_table(
        "project_knowledgebases",
        sa.Column(
            "project_id",
            sa.String(),
            sa.ForeignKey("projects.project_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "knowledgebase_id",
            sa.String(),
            sa.ForeignKey("knowledgebases.knowledgebase_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("assigned_by", sa.String(), sa.ForeignKey("users.email"), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    )


def downgrade() -> None:
    """Remove project assignments, preserving knowledgebases."""
    op.drop_table("project_knowledgebases")
