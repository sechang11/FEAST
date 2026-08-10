"""Web backend for the FEAST site and the free calculator.

The calculator runs the *same* native library and the same feastpy code path as
the desktop app -- there is no second implementation to drift. That is the whole
reason the solver logic lives in the package rather than in the GUI.

    python -m uvicorn server:app --port 8000        (from this directory)

Free-tier limits are by problem size, not by feature: the calculator does the
real thing, and the wall is honest.
"""
from __future__ import annotations

import io
import sys
import time
from pathlib import Path

import numpy as np
import scipy.sparse as sp
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "python"))

import feastpy                      # noqa: E402
from feastpy import matrixio        # noqa: E402

# ---- free-tier limits -------------------------------------------------------
MAX_DENSE_N = 500          # a dense 500x500 solve is ~seconds
MAX_SPARSE_N = 20_000
MAX_NNZ = 400_000
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_M0 = 300
SOLVE_TIMEOUT_S = 30

app = FastAPI(title="FEAST", docs_url=None, redoc_url=None)


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
    tmp = HERE / "_upload.tmp"
    try:
        # matrixio owns every format quirk (banner-less .mtx, Fortran D
        # exponents); going through it keeps the web and desktop paths identical.
        tmp.write_text(text, encoding="utf-8")
        tmp_named = tmp.with_suffix(".mtx")
        tmp.replace(tmp_named)
        M = matrixio.load_matrix(tmp_named)
    except matrixio.MatrixLoadError as exc:
        raise HTTPException(400, f"Could not read {what}: {exc}")
    finally:
        for p in (HERE / "_upload.tmp", HERE / "_upload.mtx"):
            p.unlink(missing_ok=True)

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
def api_bounds(req: SolveRequest):
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
def api_estimate(req: SolveRequest):
    A = _parse(req.matrix, "The matrix")
    B = _parse(req.b_matrix, "The B matrix") if req.b_matrix else None
    if req.emin >= req.emax:
        raise HTTPException(400, "E min must be less than E max.")
    t0 = time.perf_counter()
    n = feastpy.estimate_count(A, req.emin, req.emax, B,
                               contour_points=req.contour_points)
    return {"count": int(n), "seconds": time.perf_counter() - t0}


@app.post("/api/solve")
def api_solve(req: SolveRequest):
    A = _parse(req.matrix, "The matrix")
    B = _parse(req.b_matrix, "The B matrix") if req.b_matrix else None
    if req.emin >= req.emax:
        raise HTTPException(400, "E min must be less than E max.")

    m0 = max(1, min(int(req.m0), MAX_M0, int(A.shape[0])))
    params = dict(emin=req.emin, emax=req.emax, m0=m0,
                  contour_points=req.contour_points,
                  tol_exponent=req.tol_exponent, max_loops=req.max_loops)

    # Same child-process runner the desktop app uses, so a runaway solve can be
    # killed rather than pinning a request thread forever.
    handle = feastpy.runner.start_solve(A, B, params)
    convergence, t0 = [], time.perf_counter()
    result = None
    while time.perf_counter() - t0 < SOLVE_TIMEOUT_S:
        out = handle.poll(0.2)
        if out is None:
            continue
        if out[0] == "progress":
            convergence.append(out[1])
            continue
        kind, payload, secs = out
        handle.close()
        if kind == "error":
            raise HTTPException(500, f"Solver failed: {payload}")
        result = (payload, secs)
        break

    if result is None:
        handle.cancel()
        handle.close()
        raise HTTPException(408,
                            f"The solve exceeded the {SOLVE_TIMEOUT_S}s free-tier "
                            "limit. Try a narrower interval, a smaller M0, or use "
                            "the desktop app, which has no time limit.")

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
    return {"max_dense_n": MAX_DENSE_N, "max_sparse_n": MAX_SPARSE_N,
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


STATIC = HERE / "static"
if STATIC.is_dir():
    app.mount("/", StaticFiles(directory=str(STATIC), html=True), name="static")
