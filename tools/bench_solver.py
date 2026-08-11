"""Compare FEAST's iterative and direct sparse solvers.

    python tools/bench_solver.py <arch-tag>

The web calculator's practical ceiling is set by how fast a solve is, not by
how big the matrix is. IFEAST (iterative, no MKL) is the portable path; the
direct PARDISO path needs MKL but is far quicker on larger problems. This
measures both so the server's limits can be set from evidence.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import numpy as np
import scipy.sparse as sp

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))

ARCH = sys.argv[1] if len(sys.argv) > 1 else "linux-x64"
soname = {"win32": "libfeast.dll", "darwin": "libfeast.dylib"}.get(sys.platform, "libfeast.so")
os.environ["FEAST_LIBRARY"] = str(ROOT / "4.0" / "lib" / ARCH / soname)

import feastpy            # noqa: E402
from feastpy import raw   # noqa: E402


def laplacian(n):
    return sp.diags([np.full(n - 1, -1.0), np.full(n, 2.0), np.full(n - 1, -1.0)],
                    [-1, 0, 1], format="csr")


def direct_solve(A, emin, emax, m0):
    """Call the PARDISO-backed routine, which only exists in an MKL build."""
    n = A.shape[0]
    Au = sp.triu(A, format="csr")
    Au.sort_indices()
    fpm = raw.new_fpm(fpm_1=0, fpm_2=8, fpm_3=12, fpm_4=20)
    lam = np.zeros(m0)
    q = np.zeros((n, m0), order="F")
    res = np.zeros(m0)
    t0 = time.perf_counter()
    out = raw.call("dfeast_scsrev", UPLO="U", N=n,
                   sa=np.ascontiguousarray(Au.data),
                   isa=np.ascontiguousarray(Au.indptr + 1, dtype=np.int32),
                   jsa=np.ascontiguousarray(Au.indices + 1, dtype=np.int32),
                   fpm=fpm, epsout=0.0, loop=0, Emin=emin, Emax=emax, M0=m0,
                   **{"lambda": lam}, q=q, mode=0, res=res, info=0)
    return time.perf_counter() - t0, out["info"], out["mode"]


print(f"--- {ARCH} ---")
print(f"{'size':>8}  {'iterative (IFEAST)':>26}  {'direct (PARDISO)':>26}")
for n, hi in ((1000, 0.01), (5000, 0.002), (20000, 0.0002), (50000, 0.00005)):
    A = laplacian(n)
    est = feastpy.estimate_count(A, 0.0, hi)
    m0 = max(10, int(est * 1.5) + 5)

    t0 = time.perf_counter()
    r = feastpy.eigsh_interval(A, 0.0, hi, m0=m0)
    ti = time.perf_counter() - t0
    left = f"{ti:8.2f}s info={r.info} found={r.n_found:<4}"

    right = "not in this build"
    try:
        td, info, mode = direct_solve(A, 0.0, hi, m0)
        right = f"{td:8.2f}s info={info} found={mode:<4}"
    except RuntimeError:
        pass

    print(f"{n:>8}  {left:>26}  {right:>26}")
