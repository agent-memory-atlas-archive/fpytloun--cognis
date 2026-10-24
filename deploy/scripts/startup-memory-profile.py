"""Optional bounded startup capture for an operator-mounted diagnostic wrapper."""

from __future__ import annotations

import os
import runpy
import socket
import sys
import threading
import time
from typing import Any


def main() -> None:
    """Start the controller normally unless profiling explicitly selects this pod."""
    enabled = os.getenv("COGNIS_MEMORY_PROFILING", "").lower() in {"true", "1"}
    selected = os.getenv("COGNIS_MEMORY_PROFILE_POD", "")
    if not enabled or (selected and selected != socket.gethostname()):
        # Do not import Memray or retain the wrapper in the ordinary process.
        os.execv("/opt/venv/bin/cognis-controller", ["cognis-controller", "serve"])
        return

    import memray

    path = f"/cognis-profile-data/{socket.gethostname()}-{time.time_ns()}.bin"
    tracker: Any = memray.Tracker(path, trace_python_allocators=True)
    tracker.__enter__()
    lock = threading.Lock()

    def stop() -> None:
        nonlocal tracker
        with lock:
            if tracker is not None:
                try:
                    tracker.__exit__(None, None, None)
                finally:
                    tracker = None

    timer = threading.Timer(90, stop)
    timer.daemon = True
    timer.start()
    try:
        sys.argv = ["/opt/venv/bin/cognis-controller", "serve"]
        runpy.run_path(sys.argv[0], run_name="__main__")
    finally:
        timer.cancel()
        stop()


if __name__ == "__main__":
    main()
