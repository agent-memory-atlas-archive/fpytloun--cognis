"""Idempotent artifact revision and content project schema, shared by bootstrap and Alembic."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from cognis.store.models import ARTIFACT_LIVE_SUPERSEDES_PREDICATE

# Project membership is backfilled only from work that was already shared with
# its project. Private chats and tasks inside a project keep private outputs.
_BACKFILL_DELIVERABLE_PROJECTS = """
UPDATE deliverables SET project_id = COALESCE(
    (SELECT t.project_id FROM tasks t JOIN step_runs r ON r.task_id = t.task_id
     WHERE r.step_run_id = deliverables.step_run_id
     AND t.visibility = 'project' AND t.project_id IS NOT NULL),
    (SELECT c.project_id FROM conversations c
     WHERE c.conversation_id = deliverables.conversation_id
     AND c.visibility = 'project' AND c.project_id IS NOT NULL))
WHERE project_id IS NULL
"""

_BACKFILL_ARTIFACT_PROJECTS = """
UPDATE artifacts SET project_id = COALESCE(
    (SELECT d.project_id FROM deliverables d WHERE d.deliverable_id = artifacts.artifact_id),
    CASE WHEN artifacts.purpose IN ('artifact_publish', 'artifact_write') THEN
        (SELECT c.project_id FROM conversations c
         WHERE c.conversation_id = artifacts.conversation_id
         AND c.visibility = 'project' AND c.project_id IS NOT NULL)
    END)
WHERE project_id IS NULL
"""


def ensure_content_revision_schema(connection: Connection) -> None:
    """Add artifact lineage and document project columns, backfill, and index."""

    tables = set(sa.inspect(connection).get_table_names())
    # Backfill only legacy rows, once, when the project column is first added.
    # Afterwards NULL means "private" and must never be reclassified.
    backfill_artifacts = backfill_deliverables = False
    if "artifacts" in tables:
        columns = {c["name"] for c in sa.inspect(connection).get_columns("artifacts")}
        for name, ddl in (
            ("lineage_id", "VARCHAR"),
            ("revision", "INTEGER NOT NULL DEFAULT 1"),
            ("supersedes_artifact_id", "VARCHAR"),
            ("project_id", "VARCHAR"),
        ):
            if name not in columns:
                connection.execute(sa.text(f"ALTER TABLE artifacts ADD COLUMN {name} {ddl}"))
                backfill_artifacts = backfill_artifacts or name == "project_id"
        connection.execute(
            sa.text("UPDATE artifacts SET lineage_id = artifact_id WHERE lineage_id IS NULL")
        )
        connection.execute(
            sa.text(
                "CREATE INDEX IF NOT EXISTS ix_artifacts_lineage ON artifacts (lineage_id, revision)"
            )
        )
        connection.execute(
            sa.text("CREATE INDEX IF NOT EXISTS ix_artifacts_project ON artifacts (project_id)")
        )
        if "status" in columns:
            connection.execute(
                sa.text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_artifacts_live_supersedes "
                    "ON artifacts (supersedes_artifact_id) "
                    f"WHERE {ARTIFACT_LIVE_SUPERSEDES_PREDICATE}"
                )
            )
    if "deliverables" in tables:
        columns = {c["name"] for c in sa.inspect(connection).get_columns("deliverables")}
        if "project_id" not in columns:
            connection.execute(sa.text("ALTER TABLE deliverables ADD COLUMN project_id VARCHAR"))
            backfill_deliverables = True
        connection.execute(
            sa.text(
                "CREATE INDEX IF NOT EXISTS ix_deliverables_project ON deliverables (project_id)"
            )
        )
    required = {"artifacts", "deliverables", "tasks", "step_runs", "conversations"}
    if not (backfill_artifacts or backfill_deliverables) or not required <= tables:
        return
    project_columns = {
        table: {c["name"] for c in sa.inspect(connection).get_columns(table)}
        for table in ("tasks", "conversations")
    }
    if not all({"project_id", "visibility"} <= cols for cols in project_columns.values()):
        return
    if backfill_deliverables:
        connection.execute(sa.text(_BACKFILL_DELIVERABLE_PROJECTS))
    if backfill_artifacts:
        connection.execute(sa.text(_BACKFILL_ARTIFACT_PROJECTS))
