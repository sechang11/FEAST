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
    """An interval search or a disc search -- the region decides which.

    `emin`/`emax` is the Hermitian case: real eigenvalues, so the region is a
    segment of the real line. `center_re`/`center_im`/`radius` is the general
    case, where the spectrum is not on a line and the contour is a circle in
    the plane. Both are optional here and validated in `region_of` so that a
    request giving neither, or both, gets an explanation rather than a 422
    naming a field the page never showed.
    """

    matrix: str = Field(..., description="Matrix Market or bare coordinate text")
    b_matrix: str | None = None
    emin: float | None = None
    emax: float | None = None
    center_re: float | None = None
    center_im: float | None = None
    radius: float | None = None
    m0: int = 40
    contour_points: int = Field(8, ge=2, le=32)
    tol_exponent: int = Field(12, ge=1, le=16)
    max_loops: int = Field(20, ge=1, le=50)

    @property
    def is_disc(self) -> bool:
        return self.radius is not None


def region_of(req: SolveRequest) -> dict:
    """The solver kwargs for this request's search region, or a 400."""
    if req.is_disc:
        if req.emin is not None or req.emax is not None:
            raise HTTPException(400, "Give either an interval or a disc, not both.")
        if req.radius <= 0:
            raise HTTPException(400, "The disc radius must be greater than zero.")
        return {"center": complex(req.center_re or 0.0, req.center_im or 0.0),
                "radius": float(req.radius)}
    if req.emin is None or req.emax is None:
        raise HTTPException(400, "Give an interval (E min and E max) or a "
                                 "search disc (centre and radius).")
    if req.emin >= req.emax:
        raise HTTPException(400, "E min must be less than E max.")
    return {"emin": float(req.emin), "emax": float(req.emax)}


def _parse(text: str, what: str, *, require_hermitian: bool = True):
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

    # Only the interval routines need the symmetry: their eigenvalues are real
    # because the matrix is Hermitian, and the whole idea of searching a
    # segment of the real line depends on that. A disc search is precisely the
    # case where the requirement does not apply, so enforcing it there would
    # reject exactly the matrices the mode exists for.
    if require_hermitian and not _is_hermitian(M):
        raise HTTPException(400, f"{what} is not Hermitian, so its eigenvalues "
                                 "are not real and there is no interval to "
                                 "search. Use a disc in the complex plane.")
    return M


def _is_hermitian(M) -> bool:
    """Hermitian, and nothing weaker.

    check_symmetry reports (symmetric, Hermitian) and the two come apart for
    complex matrices: A == A.T with A != A.H is *complex symmetric*, whose
    spectrum is complex. Accepting `sym or herm` therefore let such a matrix
    into the interval routines, which assume real eigenvalues -- and FEAST
    duly returned a set of real numbers for a spectrum reaching |imag| = 12.
    No error, no warning, just wrong answers. Only `herm` decides.

    A real symmetric matrix is Hermitian (conjugation is a no-op), so the
    ordinary case is unaffected.
    """
    _, herm = matrixio.check_symmetry(M)
    return bool(herm)


@app.post("/api/bounds")
def api_bounds(req: SolveRequest, request: Request):
    """Where the spectrum is, before anything has been solved.

    Reports whether the matrix is Hermitian as well, because that is what
    decides which search the user should be offered -- and getting it from the
    data beats asking someone to classify their own matrix.
    """
    rate_limit(request)
    A = _parse(req.matrix, "The matrix", require_hermitian=False)
    B = _parse(req.b_matrix, "The B matrix", require_hermitian=False)         if req.b_matrix else None

    hermitian = _is_hermitian(A)

    out = {"n": int(A.shape[0]),
           "sparse": bool(sp.issparse(A)),
           "nnz": int(A.nnz) if sp.issparse(A) else int(A.size),
           "generalized": B is not None,
           "hermitian": hermitian,
           "complex": bool(np.iscomplexobj(
               A.data if sp.issparse(A) else A))}

    # A disc always makes sense; an interval only for a Hermitian matrix.
    centre, radius = feastpy.spectral_disc(A, B)
    out["center_re"], out["center_im"] = centre.real, centre.imag
    out["radius"] = radius
    # Gershgorin bounds A, not the pencil A - lambda B: for a generalized
    # problem the eigenvalues are scaled by B and routinely fall outside this
    # disc -- measured at 4 of 20 inside on a random pencil. The page must not
    # call it a bound in that case, so the guarantee travels with the number.
    out["disc_is_bound"] = B is None

    if hermitian:
        try:
            lo, hi = feastpy.spectral_bounds(A, B)
            out["emin"], out["emax"] = lo, hi
        except RuntimeError as exc:
            # Not fatal: the disc bounds above still give the page something
            # to draw, so degrade to disc-only rather than failing the request.
            out["bounds_error"] = str(exc)
    return out


@app.post("/api/estimate")
def api_estimate(req: SolveRequest, request: Request):
    rate_limit(request)
    if req.is_disc:
        # fpm(14)=2 is defined for the Hermitian interval routines only. There
        # is no cheap count for a disc, and inventing one by solving would
        # defeat the point of an estimate.
        raise HTTPException(400, "Counting without solving is only available "
                                 "for an interval search.")
    A = _parse(req.matrix, "The matrix")
    B = _parse(req.b_matrix, "The B matrix") if req.b_matrix else None
    if req.emin is None or req.emax is None:
        raise HTTPException(400, "Give an interval (E min and E max).")
    if req.emin >= req.emax:
        raise HTTPException(400, "E min must be less than E max.")
    t0 = time.perf_counter()
    n = feastpy.estimate_count(A, req.emin, req.emax, B,
                               contour_points=req.contour_points)
    return {"count": int(n), "seconds": time.perf_counter() - t0}


@app.post("/api/solve")
def api_solve(req: SolveRequest, request: Request):
    rate_limit(request)
    region = region_of(req)
    A = _parse(req.matrix, "The matrix", require_hermitian=not req.is_disc)
    B = _parse(req.b_matrix, "The B matrix", require_hermitian=not req.is_disc)         if req.b_matrix else None

    m0 = max(1, min(int(req.m0), MAX_M0, int(A.shape[0])))
    params = dict(m0=m0, contour_points=req.contour_points,
                  tol_exponent=req.tol_exponent, max_loops=req.max_loops,
                  **region)

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
        bounds=_region_bounds(A, B, req),
        bounds_guaranteed=B is None, **region)

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
        # A disc search returns complex eigenvalues; float() on those raises,
        # so the shape of this field follows the mode: [re, im] pairs for a
        # disc, plain numbers for an interval.
        "eigenvalues": ([[float(v.real), float(v.imag)]
                         for v in np.asarray(r.eigenvalues)]
                        if req.is_disc else
                        [float(v) for v in r.eigenvalues]),
        "complex_eigenvalues": bool(req.is_disc),
        "residuals": [float(v) for v in r.residuals],
        "convergence": convergence,
    }


def _region_bounds(A, B, req: SolveRequest):
    """The whole-spectrum region, for diagnose()'s "look here instead" advice.

    Cheap (one pass over the nonzeros), and only consulted when a solve has
    already failed, so it never sits in the fast path.
    """
    try:
        if req.is_disc:
            centre, radius = feastpy.spectral_disc(A, B)
            return (centre, radius)
        return feastpy.spectral_bounds(A, B)
    except Exception:
        return None


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
        out = {"name": f"FEAST sample {name} (generalized)",
               "text": a.read_text(),
               "b_text": b.read_text() if b.exists() else None}
        if name == "system3":
            # system3 is FEAST's *non-Hermitian* sample: its entries are of
            # order 1e-18 and it is asymmetric by 9% of that, which is why it
            # used to be mistaken for Hermitian and searched along an interval
            # -- returning 13 of its 16 eigenvalues and reporting success.
            # These are the settings FEAST's own driver uses; the centre sits
            # 1e-4 off the real axis because a real matrix's conjugate pairs
            # would otherwise straddle the contour.
            out.update(mode="disc", center_re=0.59, center_im=1e-4, radius=0.41,
                       note="Ships with FEAST, and is non-Hermitian despite "
                            "looking symmetric: entries near 1e-18 with 9% "
                            "asymmetry. The reference driver finds 16 here.")
        else:
            out.update(mode="interval", emin=0.18, emax=1.0,
                       note="Ships with FEAST. The reference driver finds "
                            "16 eigenvalues here.")
        return out
    if name == "grcar":
        # The standard demonstration of a non-normal matrix: banded, real,
        # utterly non-symmetric, and its spectrum is a curve arcing well off
        # the real axis. Nothing here can be found by an interval search,
        # which is exactly what makes it the right sample for disc mode.
        n = 120
        ent = []
        for i in range(1, n + 1):
            if i > 1:
                ent.append((i, i - 1, -1.0))
            for k in range(0, 4):
                if i + k <= n:
                    ent.append((i, i + k, 1.0))
        rows = [f"{n} {n} {len(ent)}"] + [f"{i} {j} {v}" for i, j, v in ent]
        M = sp.coo_matrix(([v for _, _, v in ent],
                           ([i - 1 for i, _, _ in ent], [j - 1 for _, j, _ in ent])),
                          shape=(n, n)).tocsr()
        centre, radius = feastpy.spectral_disc(M)
        return {"name": "Grcar matrix (n=120)", "text": "\n".join(rows),
                "mode": "disc",
                "center_re": centre.real, "center_im": centre.imag,
                "radius": radius,
                "note": "Non-Hermitian: its eigenvalues are complex, so only a "
                        "disc search can find them. Try radius 4 about 1."}
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
