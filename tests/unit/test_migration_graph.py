from pathlib import Path

from alembic.script import ScriptDirectory


def test_migration_graph_has_one_head() -> None:
    migrations = Path(__file__).resolve().parents[2] / "cognis/store/migrations"
    script = ScriptDirectory(str(migrations))
    heads = script.get_heads()
    assert len(heads) == 1, f"Deployment requires exactly one Alembic head: {heads}"
    ancestors = {item.revision for item in script.walk_revisions()}
    assert {"157_artifact_agent_access", "157_workflow_creation_origin"} <= ancestors
