"""Join independently merged artifact and workflow-origin migrations."""

from __future__ import annotations

revision = "158_merge_artifact_workflow"
down_revision = ("157_artifact_agent_access", "157_workflow_creation_origin")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Both parents already perform their independent schema changes."""


def downgrade() -> None:
    """Restore the two parent heads without changing their schemas."""
