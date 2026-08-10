"""Worker process that runs one FEAST solve.

Launched by feastpy.runner as

    python -m feastpy._solve_child <payload.pkl> <result.pkl>

with its stdout set to a pipe by the parent. That matters: FEAST reports
convergence by printing from Fortran, and on Windows libgfortran links its own
C runtime, so redirecting the parent's file descriptors after the fact does not
touch it. Inheriting the pipe from process creation is the only redirection
every runtime agrees on.
"""
from __future__ import annotations

import pickle
import sys


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 2:
        print("usage: _solve_child <payload.pkl> <result.pkl>", file=sys.stderr)
        return 2
    payload_path, result_path = argv

    with open(payload_path, "rb") as fh:
        A, B, params = pickle.load(fh)

    try:
        from .runner import solve_blocking
        result, secs = solve_blocking(A, B, params)
        out = ("ok", result, secs)
    except Exception as exc:
        out = ("error", f"{type(exc).__name__}: {exc}", 0.0)

    # Flush first: the parent treats exit as "the result file is ready".
    sys.stdout.flush()
    with open(result_path, "wb") as fh:
        pickle.dump(out, fh)
    return 0


if __name__ == "__main__":
    sys.exit(main())
