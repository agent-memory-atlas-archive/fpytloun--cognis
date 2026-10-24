"""Artifact revision lineage and document-level project scope."""

from __future__ import annotations

from alembic import op

from cognis.store.content_revision_schema import ensure_content_revision_schema

revision = "160_content_revisions_projects"
down_revision = "159_project_knowledgebases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    ensure_content_revision_schema(op.get_bind())


def downgrade() -> None:
    op.drop_index("ix_deliverables_project", table_name="deliverables")
    with op.batch_alter_table("deliverables") as batch:
        batch.drop_column("project_id")
    op.drop_index("uq_artifacts_live_supersedes", table_name="artifacts")
    op.drop_index("ix_artifacts_project", table_name="artifacts")
    op.drop_index("ix_artifacts_lineage", table_name="artifacts")
    with op.batch_alter_table("artifacts") as batch:
        for column in ("project_id", "supersedes_artifact_id", "revision", "lineage_id"):
            batch.drop_column(column)
