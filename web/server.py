"""Web backend for the FEAST site and the free calculator.

The calculator runs the *same* native library and the same feastpy code path as
the desktop app -- there is no second implementation to drift. That is the whole
reason the solver logic lives in the package rather than in the GUI.

    python -m uvicorn server:app --port 8000        (from this directory)

Free-tier limits are by problem size, not by feature: the calculator does the
real thing, and the wall is honest.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import threading
import time
from collections import defaultdict, deque
from pathlib import Path

import numpy as np
import scipy.sparse as sp
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "python"))

import feastpy                      # noqa: E402
from feastpy import matrixio        # noqa: E402

# ---- free-tier limits -------------------------------------------------------
# Measured on the reference build (OpenBLAS, iterative inner solver), sizing M0
# from the estimator as the UI does:
#
#   sparse n=1,000   ~1.8 s      dense n=100   ~1.7 s
#   sparse n=5,000   >30 s       dense n=300   ~9.2 s
#   sparse n=20,000  >30 s       dense n=500   ~5.3 s
#
# The old ceilings (dense 500, sparse 20,000) were advertised but unreachable
# inside the time limit: a user picked an allowed size and got a timeout. Cost
# tracks how many eigenvalues are in the interval as much as the matrix size,
# so no size cap can guarantee completion -- the timeout is the real guard and
# these keep the common case inside it.
MAX_DENSE_N = 500
MAX_SPARSE_N = 5_000
MAX_NNZ = 200_000
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_M0 = 300
SOLVE_TIMEOUT_S = 30

# A solve is real CPU work, so the expensive endpoints are rate limited per
# client and the number running at once is capped. Without the concurrency cap
# a handful of requests can occupy every worker thread and the site stops
# responding at all.
RATE_LIMIT_REQUESTS = int(os.environ.get("FEAST_RATE_LIMIT", "20"))
RATE_LIMIT_WINDOW_S = 60
MAX_CONCURRENT_SOLVES = int(os.environ.get("FEAST_MAX_CONCURRENT", "4"))

# FEAST is OpenMP-parallel and will take every core it can see. On a server
# that is the wrong default: one visitor's solve would starve everyone else's,
# and MAX_CONCURRENT_SOLVES would oversubscribe the machine several times over.
# Give each solve a slice instead. Children inherit this.
_threads = os.environ.get("FEAST_SOLVE_THREADS")
if not _threads:
    _cpus = os.cpu_count() or 4
    _threads = str(max(1, _cpus // max(1, MAX_CONCURRENT_SOLVES)))
os.environ.setdefault("OMP_NUM_THREADS", _threads)

_solve_slots = threading.BoundedSemaphore(MAX_CONCURRENT_SOLVES)
_hits: dict[str, deque] = defaultdict(deque)
_hits_lock = threading.Lock()

app = FastAPI(title="FEAST", docs_url=None, redoc_url=None)


def _client_key(request: Request) -> str:
    # Behind a proxy the peer address is the proxy; trust the first hop of
    # X-Forwarded-For only when explicitly told to, so the limit cannot be
    # bypassed by spoofing the header on a direct connection.
    if os.environ.get("FEAST_TRUST_PROXY"):
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit(request: Request) -> None:
    key = _client_key(request)
    now = time.monotonic()
    with _hits_lock:
        q = _hits[key]
        while q and now - q[0] > RATE_LIMIT_WINDOW_S:
            q.popleft()
        if len(q) >= RATE_LIMIT_REQUESTS:
            retry = int(RATE_LIMIT_WINDOW_S - (now - q[0])) + 1
            raise HTTPException(429, f"Too many requests. Try again in {retry}s. "
                                     "The desktop app has no such limit.")
        q.append(now)
        if len(_hits) > 10_000:            # bound the table itself
            for k in [k for k, v in _hits.items() if not v][:5000]:
                _hits.pop(k, None)


@app.middleware("http")
async def guard(request: Request, call_next):
    """Reject oversized bodies before they are read, and set security headers."""
    if request.method == "POST":
        declared = request.headers.get("content-length")
        if declared and int(declared) > MAX_UPLOAD_BYTES * 3:
            return JSONResponse(
                {"detail": f"Request body exceeds the "
                           f"{MAX_UPLOAD_BYTES * 3 // (1024*1024)} MB limit."},
                status_code=413)
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    # The pages load nothing from anywhere else, so lock that in.
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data:; style-src 'self'; "
        "script-src 'self'; base-uri 'none'; form-action 'none'")
    return response


class SolveRequest(BaseModel):
    matrix: str = Field(..., description="Matrix Market or bare coordinate text")
    b_matrix: str | None = None
    emin: float
    emax: float
    m0: int = 40
    contour_points: int = Field(8, ge=2, le=32)
    tol_exponent: int = Field(12, ge=1, le=16)
    max_loops: int = Field(20, ge=1, le=50)


def _parse(text: str, what: str):
    if len(text.encode("utf-8", "ignore")) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"{what} is larger than the "
                                 f"{MAX_UPLOAD_BYTES // (1024*1024)} MB free-tier limit.")
    # A per-request temp directory: a fixed filename would be clobbered by
    # concurrent requests, and two users would silently read each other's
    # matrices.
    tmpdir = Path(tempfile.mkdtemp(prefix="feast-web-"))
    try:
        # matrixio owns every format quirk (banner-less .mtx, Fortran D
        # exponents); going through it keeps the web and desktop paths identical.
        target = tmpdir / "upload.mtx"
        target.write_text(text, encoding="utf-8")
        M = matrixio.load_matrix(target)
    except matrixio.MatrixLoadError as exc:
        raise HTTPException(400, f"Could not read {what}: {exc}")
    except Exception as exc:                      # malformed input, not a crash
        raise HTTPException(400, f"Could not read {what}: {exc}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    if M.shape[0] != M.shape[1]:
        raise HTTPException(400, f"{what} must be square, got "
                                 f"{M.shape[0]}x{M.shape[1]}.")
    n = M.shape[0]
    if sp.issparse(M):
        if n > MAX_SPARSE_N:
            raise HTTPException(413, f"{what} is {n}x{n}; the free calculator "
                                     f"handles sparse matrices up to {MAX_SPARSE_N}.")
        if M.nnz > MAX_NNZ:
            raise HTTPException(413, f"{what} has {M.nnz:,} nonzeros; the free "
                                     f"limit is {MAX_NNZ:,}.")
    elif n > MAX_DENSE_N:
        raise HTTPException(413, f"{what} is {n}x{n}; the free calculator handles "
                                 f"dense matrices up to {MAX_DENSE_N}x{MAX_DENSE_N}. "
                                 "The desktop app has no such limit.")

    sym, herm = matrixio.check_symmetry(M)
    if not (sym or herm):
        raise HTTPException(400, f"{what} is neither symmetric nor Hermitian. "
                                 "These solvers require one.")
    return M


@app.post("/api/bounds")
def api_bounds(req: SolveRequest, request: Request):
    rate_limit(request)
    A = _parse(req.matrix, "The matrix")
    B = _parse(req.b_matrix, "The B matrix") if req.b_matrix else None
    try:
        lo, hi = feastpy.spectral_bounds(A, B)
    except RuntimeError as exc:
        raise HTTPException(400, str(exc))
    return {"emin": lo, "emax": hi, "n": int(A.shape[0]),
            "sparse": bool(sp.issparse(A)),
            "nnz": int(A.nnz) if sp.issparse(A) else int(A.size),
            "generalized": B is not None}


@app.post("/api/estimate")
def api_estimate(req: SolveRequest, request: Request):
    rate_limit(request)
    A = _parse(req.matrix, "The matrix")
    B = _parse(req.b_matrix, "The B matrix") if req.b_matrix else None
    if req.emin >= req.emax:
        raise HTTPException(400, "E min must be less than E max.")
    t0 = time.perf_counter()
    n = feastpy.estimate_count(A, req.emin, req.emax, B,
                               contour_points=req.contour_points)
    return {"count": int(n), "seconds": time.perf_counter() - t0}


@app.post("/api/solve")
def api_solve(req: SolveRequest, request: Request):
    rate_limit(request)
    A = _parse(req.matrix, "The matrix")
    B = _parse(req.b_matrix, "The B matrix") if req.b_matrix else None
    if req.emin >= req.emax:
        raise HTTPException(400, "E min must be less than E max.")

    m0 = max(1, min(int(req.m0), MAX_M0, int(A.shape[0])))
    params = dict(emin=req.emin, emax=req.emax, m0=m0,
                  contour_points=req.contour_points,
                  tol_exponent=req.tol_exponent, max_loops=req.max_loops)

    # Cap simultaneous solves: each one is a child process doing real numerical
    # work, and without this a few requests saturate the machine.
    if not _solve_slots.acquire(timeout=15):
        raise HTTPException(503, "The calculator is busy. Try again shortly, or "
                                 "use the desktop app, which runs locally.")
    # Same child-process runner the desktop app uses, so a runaway solve can be
    # killed rather than pinning a request thread forever.
    handle = feastpy.runner.start_solve(A, B, params)
    convergence, t0 = [], time.perf_counter()
    result = None
    try:
        while time.perf_counter() - t0 < SOLVE_TIMEOUT_S:
            out = handle.poll(0.2)
            if out is None:
                continue
            if out[0] == "progress":
                convergence.append(out[1])
                continue
            kind, payload, secs = out
            if kind == "error":
                raise HTTPException(500, f"Solver failed: {payload}")
            result = (payload, secs)
            break

        if result is None:
            handle.cancel()
            raise HTTPException(408,
                                f"The solve exceeded the {SOLVE_TIMEOUT_S}s free-tier "
                                "limit. Try a narrower interval, a smaller M0, or use "
                                "the desktop app, which has no time limit.")
    finally:
        handle.cancel()          # no-op if it already finished
        handle.close()
        _solve_slots.release()

    r, secs = result
    diag = feastpy.diagnostics.diagnose(
        r, n=int(A.shape[0]), m0=m0, contour_points=req.contour_points,
        tol_exponent=req.tol_exponent, max_loops=req.max_loops,
        emin=req.emin, emax=req.emax)

    return {
        "info": r.info,
        "message": r.message,
        "headline": diag.headline,
        "detail": diag.detail,
        "suggestions": [{"text": s.text, "param": s.param, "value": s.value}
                        for s in diag.suggestions],
        "n_found": int(r.n_found),
        "loops": int(r.loops),
        "epsout": float(r.epsout),
        "seconds": secs,
        "m0_used": m0,
        "eigenvalues": [float(v) for v in r.eigenvalues],
        "residuals": [float(v) for v in r.residuals],
        "convergence": convergence,
    }


@app.get("/api/limits")
def api_limits():
    return {"threads_per_solve": int(os.environ.get("OMP_NUM_THREADS", "1")),
            "concurrent_solves": MAX_CONCURRENT_SOLVES,
            "max_dense_n": MAX_DENSE_N, "max_sparse_n": MAX_SPARSE_N,
            "max_nnz": MAX_NNZ, "max_m0": MAX_M0,
            "timeout_s": SOLVE_TIMEOUT_S,
            "max_upload_mb": MAX_UPLOAD_BYTES // (1024 * 1024)}


@app.get("/api/samples/{name}")
def api_sample(name: str):
    """Sample matrices so the calculator works without a file to hand."""
    if name == "laplacian1d":
        n = 200
        rows = [f"{n} {n} {3*n-2}"]
        for i in range(1, n + 1):
            rows.append(f"{i} {i} 2.0")
            if i > 1:
                rows.append(f"{i} {i-1} -1.0")
            if i < n:
                rows.append(f"{i} {i+1} -1.0")
        return {"name": "1-D Laplacian (n=200)", "text": "\n".join(rows),
                "emin": 0.0, "emax": 0.02,
                "note": "Eigenvalues are 2-2cos(k*pi/201), so you can check the answer."}
    if name in ("system1", "system3"):
        data = matrixio.DATA_DIR
        a, b = data / f"{name}.mtx", data / f"{name}B.mtx"
        if not a.exists():
            raise HTTPException(404, "sample not available")
        return {"name": f"FEAST sample {name} (generalized)",
                "text": a.read_text(), "b_text": b.read_text() if b.exists() else None,
                "emin": 0.18, "emax": 1.0,
                "note": "Ships with FEAST. The reference driver finds 16 eigenvalues here."}
    raise HTTPException(404, "unknown sample")


@app.get("/api/health", include_in_schema=True)
def health():
    """Is this deployment actually able to solve anything?

    Worth its own endpoint because the two things that break a deploy both
    fail *quietly*. The pages are generated rather than committed, so a
    missing build step serves 404s from a perfectly healthy server. And
    libfeast is loaded lazily on first use, so a container with no Fortran
    library starts, serves the whole site, and only fails when a visitor
    presses Solve. Neither shows up in a normal uptime check.
    """
    out = {"site": (STATIC / "index.html").is_file(), "library": False,
           "solver": False, "detail": ""}
    try:
        from feastpy import _lib

        # load(), not the import: the module imports fine with no library on
        # disk, which is exactly how a deploy comes to look healthy and fail on
        # the first solve.
        out["library_path"] = str(_lib.load()._name)
        out["library"] = True
    except Exception as exc:
        out["detail"] = f"{type(exc).__name__}: {exc}"
        return out
    try:
        # Not just "does it load" -- does it solve? A 40x40 tridiagonal whose
        # spectrum is known in closed form; costs a millisecond.
        n = 40
        A = sp.diags([np.full(n - 1, -1.0), np.full(n, 2.0), np.full(n - 1, -1.0)],
                     [-1, 0, 1], format="csr")
        exact = np.array([2 - 2 * np.cos((k + 1) * np.pi / (n + 1)) for k in range(n)])
        want = int(((exact > 0.0) & (exact < 0.05)).sum())
        r = feastpy.eigsh_interval(A, 0.0, 0.05, m0=10)
        ok = r.info == 0 and r.n_found == want
        out["solver"] = bool(ok)
        out["detail"] = (f"found {r.n_found} of {want} eigenvalues, "
                         f"max residual {r.residuals.max():.1e}" if r.n_found
                         else f"info={r.info}")
    except Exception as exc:
        out["detail"] = f"{type(exc).__name__}: {exc}"
    return out


STATIC = HERE / "static"

# The pages are generated by build_site.py and are not committed, so a fresh
# checkout has a static/ directory with stylesheets but no HTML. Generate them
# now rather than depending on a build step: hosting platforms disagree about
# which build files they read, and a deploy that serves 404s from a working
# server is a poor way to find that out. Takes milliseconds and is idempotent.
if not (STATIC / "index.html").is_file():
    try:
        sys.path.insert(0, str(HERE))
        import build_site

        build_site.main()
        print(f"generated {STATIC} at startup", flush=True)
    except Exception as exc:                    # never block the API
        print(f"could not generate the site: {type(exc).__name__}: {exc}",
              flush=True)

        @app.get("/", include_in_schema=False)
        def _no_site():
            raise HTTPException(
                503,
                "The site's pages could not be generated. Run "
                "`python web/build_site.py`. The JSON API under /api is "
                "unaffected -- see /api/health.")

if STATIC.is_dir():
    app.mount("/", StaticFiles(directory=str(STATIC), html=True), name="static")
