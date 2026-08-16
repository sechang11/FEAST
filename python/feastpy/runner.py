"""Running a solve so that it can be cancelled and can report progress.

Two things force the solve out of this process and into a child:

1. Cancel. A FEAST call is one blocking trip into Fortran -- no callback, no
   polling point, no abort hook -- so a thread running it cannot be
   interrupted; Python cannot kill a thread that is not executing bytecode.
   (The RCI interfaces do hand control back each step, but using them means
   reimplementing the inner complex linear solves here, with different numerics
   from the routines we ship.) A process, the OS can terminate.

2. Progress. FEAST reports convergence by *printing* it. Capturing that needs
   the child's stdout to be a pipe from process creation: on Windows
   libgfortran links its own C runtime, and neither os.dup2() on our file
   descriptors nor SetStdHandle() after the fact redirects it. Both were tried.

So the child is launched with subprocess (not multiprocessing, which cannot set
the child's stdio), and the payload travels via pickle files.

The cost is that A and B are pickled to the child, so a solve briefly needs
memory for two copies. `solve_blocking` runs in-process for callers who would
rather not pay that.
"""
from __future__ import annotations

import os
import pickle
import queue as _queue
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# Set in a frozen build so the app's entry point can route straight to the
# child's main() instead of relaunching the GUI.
CHILD_ENV_FLAG = "FEASTPY_SOLVE_CHILD"


def solve_blocking(A, B, params: dict):
    """Run a solve in this process. Returns (FeastResult, seconds).

    The search region picks the routine family. `emin`/`emax` means a Hermitian
    interval on the real line; `center`/`radius` means a disc in the complex
    plane, which is what a non-Hermitian or complex-symmetric matrix needs
    because its eigenvalues do not lie on a line at all.
    """
    import scipy.sparse as sp

    from . import solver

    t0 = time.perf_counter()
    # A self-consistent problem is not a different routine, it is a loop
    # around one: the matrix depends on its own eigenvectors.
    if params.get("scf"):
        r = _solve_self_consistent(A, B, dict(params))
        return r, time.perf_counter() - t0
    # A list of matrices means a polynomial problem: A0 + lambda A1 + ...
    if isinstance(A, (list, tuple)):
        r = solver.eig_polynomial(A, **params)
        return r, time.perf_counter() - t0
    if "center" in params:
        r = solver.eig_disc(A, B=B, **params)
    else:
        fn = solver.eigsh_interval if sp.issparse(A) else solver.eigh_interval
        r = fn(A, B=B, **params)
    return r, time.perf_counter() - t0


SCF_MARKER = "FEASTPY-SCF"


def _solve_self_consistent(A, B, params: dict):
    """The nonlinear *eigenvector* problem: H(X) X = X Lambda.

    Here the matrix depends on the eigenvectors it produces -- the
    self-consistent field problem, as in Kohn-Sham DFT or Hartree-Fock. FEAST
    has no single routine for it and does not need one: the shape of the
    answer is a loop, where each pass builds H from the current density and
    solves it, until the density stops moving.

    The density is rho_i = sum_j |X_ij|^2 over the occupied states returned,
    and the coupling is a diagonal potential

        V(rho) = alpha * rho ** exponent

    which covers the textbook cases: exponent 1 is Hartree-like, 1/3 is the
    shape of LDA exchange. Successive densities are mixed rather than replaced,
    because taking the new density outright oscillates instead of converging.

    Each pass starts from the previous pass's subspace via fpm(5)=1, which is
    what makes this cheap: the eigenvectors barely move between iterations.
    """
    import numpy as np
    import scipy.sparse as sp

    from . import solver

    scf = params.pop("scf")
    alpha = float(scf.get("alpha", 1.0))
    exponent = float(scf.get("exponent", 1.0))
    mixing = float(scf.get("mixing", 0.3))
    tol = float(scf.get("tol", 1e-8))
    max_outer = int(scf.get("max_outer", 50))
    verbose = params.get("verbose", False)

    if not (0.0 < mixing <= 1.0):
        raise ValueError(f"mixing must be in (0, 1], got {mixing}")

    sparse = sp.issparse(A)
    n = A.shape[0]
    rho = np.zeros(n)
    prev = None
    last = None

    # The inner solve must not print its own table on top of ours.
    inner = dict(params, verbose=False)
    inner.pop("rule", None) if not sparse else None

    for it in range(1, max_outer + 1):
        pot = alpha * np.power(rho, exponent) if exponent != 1.0 else alpha * rho
        H = (A + sp.diags(pot, format="csr")) if sparse else (A + np.diag(pot))
        fn = solver.eigsh_interval if sparse else solver.eigh_interval
        r = fn(H, B=B, initial_subspace=prev, **inner)
        last = r
        if r.info != 0 or r.n_found == 0:
            # Report the failure from the pass that produced it rather than
            # looping on a broken state.
            break
        X = r.eigenvectors
        new_rho = np.sum(np.abs(X) ** 2, axis=1)
        delta = float(np.max(np.abs(new_rho - rho)))
        prev = X
        rho = (1.0 - mixing) * rho + mixing * new_rho
        if verbose:
            print(f"{SCF_MARKER} iter={it} delta={delta:.6e} "
                  f"found={r.n_found} lam0={r.eigenvalues[0]:.10g}", flush=True)
        if delta < tol:
            break

    if last is not None:
        last.scf_iterations = it
        last.scf_delta = delta if last.info == 0 and last.n_found else float("nan")
        last.scf_density = rho
        last.scf_converged = bool(last.info == 0 and last.n_found and delta < tol)
    return last


def parse_progress(line: str) -> Optional[dict]:
    """Also recognises the self-consistent loop's own progress lines."""
    if line.lstrip().startswith(SCF_MARKER):
        out: dict = {"scf": True}
        for tok in line.split()[1:]:
            if "=" not in tok:
                continue
            k, v = tok.split("=", 1)
            try:
                out[k] = int(v) if k in ("iter", "found") else float(v)
            except ValueError:
                pass
        return out
    return _parse_feast_table(line)


def _parse_feast_table(line: str) -> Optional[dict]:
    """Parse one row of FEAST's runtime convergence table.

    With fpm(1)=1 FEAST prints, per refinement loop:

        #It | #Eig |     Trace     |  Error-Trace  |  Max-Residual
          0    16    9.5174696E+00   1.0000000E+00   8.8472770E-02

    Everything else it prints -- banners, the parameter table, IFEAST's inner
    '#it    19; res min= ...' lines -- has a different shape and is ignored.
    """
    parts = line.split()
    if len(parts) != 5:
        return None
    try:
        loop, n_eig = int(parts[0]), int(parts[1])
        trace, err, res = (float(p.replace("D", "E").replace("d", "e"))
                           for p in parts[2:])
    except ValueError:
        return None
    if loop < 0 or n_eig < 0:
        return None
    return {"loop": loop, "n_eig": n_eig, "trace": trace,
            "error_trace": err, "residual": res}


@dataclass
class SolveHandle:
    """A running solve that can be cancelled and polled for progress."""

    process: Any
    queue: Any
    result_path: Path
    payload_path: Path
    started: float
    reader: Any = None
    _done: bool = field(default=False, init=False)

    def poll(self, timeout: float = 0.1):
        """Return one of:
            ('progress', record, 0.0)   a convergence-table row
            ('ok', FeastResult, secs)   finished
            ('error', message, 0.0)     failed
            None                        still running
        """
        try:
            return self.queue.get(timeout=timeout)
        except _queue.Empty:
            pass

        if self.process.poll() is None:
            return None
        if self._done:
            return None
        self._done = True

        # Drain anything the reader queued between the checks above.
        try:
            return self.queue.get_nowait()
        except _queue.Empty:
            pass

        if self.result_path.exists():
            try:
                with self.result_path.open("rb") as fh:
                    return pickle.load(fh)
            except Exception as exc:
                return ("error", f"could not read solver result: {exc}", 0.0)
        return ("error",
                f"solver process ended without a result (exit code {self.process.returncode})",
                0.0)

    @property
    def running(self) -> bool:
        return self.process.poll() is None

    def cancel(self, grace: float = 0.5) -> None:
        """Terminate the solve. Safe to call more than once."""
        if self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            self.process.kill()                 # ignored SIGTERM: escalate
            try:
                self.process.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                pass

    def close(self) -> None:
        try:
            if self.process.stdout is not None:
                self.process.stdout.close()
        except Exception:
            pass
        for p in (self.result_path, self.payload_path):
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass


def _reader(stream, q):
    """Forward the child's printed convergence rows to the parent."""
    try:
        for line in stream:
            rec = parse_progress(line)
            if rec is not None:
                q.put(("progress", rec, 0.0))
    except Exception:
        pass


def _child_command(payload: Path, result: Path) -> list[str]:
    if getattr(sys, "frozen", False):
        # In a bundled app sys.executable is the app itself; the entry point
        # checks CHILD_ENV_FLAG and dispatches to the child's main().
        return [sys.executable, str(payload), str(result)]
    return [sys.executable, "-m", "feastpy._solve_child", str(payload), str(result)]


def start_solve(A, B, params: dict, *, progress: bool = True) -> SolveHandle:
    """Launch a cancellable solve in a child process."""
    tmp = Path(tempfile.mkdtemp(prefix="feastpy-"))
    payload_path, result_path = tmp / "payload.pkl", tmp / "result.pkl"

    # fpm(1)=1 makes FEAST print the convergence table we parse.
    params = dict(params, verbose=bool(progress))
    with payload_path.open("wb") as fh:
        pickle.dump((A, B, params), fh, protocol=pickle.HIGHEST_PROTOCOL)

    env = dict(os.environ)
    env[CHILD_ENV_FLAG] = "1"
    # libgfortran block-buffers a pipe, which would withhold the whole table
    # until exit and make the progress plot useless.
    env.setdefault("GFORTRAN_UNBUFFERED_PRECONNECTED", "y")
    pkg_parent = str(Path(__file__).resolve().parent.parent)
    env["PYTHONPATH"] = os.pathsep.join(
        [pkg_parent] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))

    kwargs = {}
    if sys.platform == "win32":
        # Without this a GUI app pops a console window for every solve.
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

    proc = subprocess.Popen(
        _child_command(payload_path, result_path),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, env=env, cwd=str(tmp), **kwargs)

    q: Any = _queue.Queue()
    reader = threading.Thread(target=_reader, args=(proc.stdout, q), daemon=True)
    reader.start()

    return SolveHandle(process=proc, queue=q, result_path=result_path,
                       payload_path=payload_path, started=time.perf_counter(),
                       reader=reader)
