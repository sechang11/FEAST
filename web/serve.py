"""Start the web calculator. Entry point for hosting platforms.

    python web/serve.py

Deliberately a Python file rather than a shell command, because a start command
has to survive being run *without* a shell. A command like

    PYTHONPATH=python python -m uvicorn server:app --port $PORT

works in a terminal and fails on a platform that execs it directly: the
environment prefix is taken as the name of the program, and `$PORT` is passed
through as four literal characters. Both have to be handled in Python instead.

Nothing here needs PYTHONPATH -- server.py puts the package on the path itself.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> None:
    import uvicorn

    # server.py lives here, and imports `feastpy` from ../python on its own.
    sys.path.insert(0, str(HERE))

    # The platform assigns the port at runtime; 8000 is for a local run.
    port = int(os.environ.get("PORT", "8000"))
    host = os.environ.get("HOST", "0.0.0.0")

    print(f"FEAST web calculator on {host}:{port}", flush=True)
    uvicorn.run("server:app", host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
