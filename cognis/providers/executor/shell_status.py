"""Bind shell status to its authenticated controller-side executor transport."""

from typing import Any


def bind_shell_status(snapshot: dict[str, Any], executor_id: str) -> dict[str, Any]:
    """Project connection identity without trusting the executor's local label.

    Standalone executors use a process-local label such as ``remote``. The
    authenticated transport owns routing identity; user/conversation ownership
    remains untouched and must still be checked by consumers.
    """
    shells = snapshot.get("shells")
    if not isinstance(shells, list):
        return snapshot
    return {
        **snapshot,
        "shells": [
            {
                **row,
                "reported_executor_id": row.get("executor_id"),
                "executor_id": executor_id,
            }
            if isinstance(row, dict)
            else row
            for row in shells
        ],
    }
