import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from cognis.store.hook_schema import ensure_hook_handoff


def test_upgrade_old_metadata_schema_is_idempotent_and_scope_is_unique():
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "CREATE TABLE agent_hook_runs (run_id TEXT PRIMARY KEY, owner_email TEXT, "
                "agent_id TEXT, hook_id TEXT, conversation_id TEXT, child_conversation_id TEXT, created_at TEXT)"
            )
        )
        ensure_hook_handoff(connection)
        ensure_hook_handoff(connection)
        columns = {
            column["name"] for column in sa.inspect(connection).get_columns("agent_hook_runs")
        }
        assert {"handoff", "fork_slot"} <= columns
        connection.execute(
            sa.text(
                "INSERT INTO agent_hook_runs(run_id, fork_slot) VALUES ('run-first', 'scope-first')"
            )
        )
        with pytest.raises(IntegrityError):
            connection.execute(
                sa.text(
                    "INSERT INTO agent_hook_runs(run_id, fork_slot) VALUES ('run-second', 'scope-first')"
                )
            )
    engine.dispose()
