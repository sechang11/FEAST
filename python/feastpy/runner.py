"""Running a solve so that it can actually be cancelled.

A FEAST call is a single blocking trip into Fortran. Once it starts there is no
callback and no polling point, so a thread running it cannot be interrupted --
Python cannot kill a thread that is not executing bytecode, and the simple
interfaces expose no abort hook. (FEAST's RCI interfaces do hand control back
each step, but using them means reimplementing the inner complex linear solves
here, with different numerics from the routines we ship.)

So the solve runs in a child *process*, which the OS can terminate outright.

The cost is that A and B are pickled to the child, so a solve briefly needs
memory for two copies of the matrices. For interactive problems that is a fair
trade for a Cancel button that always works; `solve_blocking` is available when
it is not.
"""
from __future__ import annotations

import multiprocessing as mp
import queue as _queue
import time
from dataclasses import dataclass
from typing import Any, Optional


def solve_blocking(A, B, params: dict):
    """Run a solve in this process. Returns (FeastResult, seconds)."""
    import scipy.sparse as sp

    from . import solver

    t0 = time.perf_counter()
    fn = solver.eigsh_interval if sp.issparse(A) else solver.eigh_interval
    r = fn(A, B=B, **params)
    return r, time.perf_counter() - t0


def _child(A, B, params, q):
    """Entry point in the child process. Must be importable at module level so
    Windows' spawn start method can pickle a reference to it."""
    try:
        r, secs = solve_blocking(A, B, params)
        q.put(("ok", r, secs))
    except Exception as exc:
        q.put(("error", f"{type(exc).__name__}: {exc}", 0.0))


@dataclass
class SolveHandle:
    """A running solve that can be cancelled."""

    process: Any
    queue: Any
    started: float

    def poll(self, timeout: float = 0.1):
        """Return ('ok', result, secs) / ('error', msg, 0) / None if still running.

        A dead child with an empty queue means it was killed or crashed; that is
        reported as an error rather than hanging forever.
        """
        try:
            return self.queue.get(timeout=timeout)
        except _queue.Empty:
            pass
        if not self.process.is_alive():
            code = self.process.exitcode
            if code == 0:
                # Finished but the result is still in flight down the pipe.
                try:
                    return self.queue.get(timeout=2.0)
                except _queue.Empty:
                    return ("error", "solver process ended without returning a result", 0.0)
            return ("error", f"solver process died (exit code {code})", 0.0)
        return None

    @property
    def running(self) -> bool:
        return self.process.is_alive()

    def cancel(self, grace: float = 0.5) -> None:
        """Terminate the solve. Safe to call more than once."""
        if not self.process.is_alive():
            return
        self.process.terminate()
        self.process.join(grace)
        if self.process.is_alive():        # ignored SIGTERM: escalate
            try:
                self.process.kill()
            except Exception:
                pass
            self.process.join(grace)

    def close(self) -> None:
        try:
            self.process.join(0.1)
            self.process.close()
        except Exception:
            pass


def start_solve(A, B, params: dict) -> SolveHandle:
    """Launch a cancellable solve in a child process."""
    # 'spawn' everywhere: it is the only option on Windows, and forking a
    # process that has OpenMP threads and a loaded BLAS is a known way to
    # deadlock on Linux.
    ctx = mp.get_context("spawn")
    q = ctx.Queue()
    p = ctx.Process(target=_child, args=(A, B, params, q), daemon=True)
    p.start()
    return SolveHandle(process=p, queue=q, started=time.perf_counter())
