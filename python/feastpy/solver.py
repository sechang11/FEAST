"""High-level FEAST interface.

FEAST finds every eigenvalue inside a user-chosen interval (or complex contour)
rather than "the k smallest". So the API here takes an interval, not a count.

    from feastpy import eigh_interval
    r = eigh_interval(A, emin=0.0, emax=0.05)
    r.eigenvalues, r.eigenvectors, r.residuals
"""
from __future__ import annotations

import ctypes
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np

from . import _lib

_i = ctypes.c_int
_d = ctypes.c_double


def _iptr(x):
    return ctypes.byref(_i(x)) if not isinstance(x, np.ndarray) else x.ctypes.data_as(ctypes.POINTER(_i))


class FeastError(RuntimeError):
    def __init__(self, info: int):
        self.info = info
        super().__init__(f"{info}: {explain_info(info)}")


def explain_info(info: int) -> str:
    """Turn FEAST's `info` code into something a GUI can show a user."""
    if info == 0:
        return "success"
    table = {
        202: "problem with size of the system N (N <= 0)",
        201: "problem with size of initial subspace M0 (M0 <= 0 or M0 > N)",
        200: "problem with emin/emax (emin >= emax)",
        6: "converged, but subspace is not fully bi-orthonormal",
        4: "only the subspace has been returned",
        3: "size of the subspace M0 is too small - increase it and retry",
        2: "no convergence: maximum refinement loops reached",
        1: "no eigenvalue found in the search interval",
        -1: "internal error: memory allocation failed",
        -2: "internal error in the reduced eigenvalue solver",
        -3: "internal error in the reduced eigenvalue solver (LAPACK)",
    }
    if info in table:
        return table[info]
    if 100 <= info <= 199:
        return f"invalid value in input parameter fpm[{info - 100}]"
    if info < 0:
        return f"internal error (info={info})"
    return f"unknown status (info={info})"


@dataclass
class FeastResult:
    eigenvalues: np.ndarray
    eigenvectors: np.ndarray
    residuals: np.ndarray
    n_found: int
    loops: int
    epsout: float
    info: int
    subspace_used: int

    @property
    def converged(self) -> bool:
        return self.info == 0

    @property
    def message(self) -> str:
        return explain_info(self.info)


def _make_fpm(contour_points: int, tol_exponent: int, max_loops: int,
              verbose: bool, count_only: bool = False) -> np.ndarray:
    """fpm is FEAST's 64-entry parameter array; feastinit fills in the defaults.

    Note the index shift: the documentation uses Fortran's fpm(1..64), so
    fpm(N) is fpm[N-1] here.
    """
    fpm = np.zeros(64, dtype=np.int32)
    _lib.sym("feastinit")(fpm.ctypes.data_as(ctypes.POINTER(_i)))
    fpm[0] = 1 if verbose else 0     # fpm(1)  runtime printing
    fpm[1] = contour_points          # fpm(2)  quadrature points on the contour
    fpm[2] = tol_exponent            # fpm(3)  stop at 1e-<tol_exponent>
    fpm[3] = max_loops               # fpm(4)  max refinement loops
    if count_only:
        fpm[13] = 2                  # fpm(14) stochastic eigenvalue-count estimate
    return fpm


def eigh_interval(
    A: np.ndarray,
    emin: float,
    emax: float,
    B: Optional[np.ndarray] = None,
    *,
    m0: Optional[int] = None,
    contour_points: int = 8,
    tol_exponent: int = 12,
    max_loops: int = 20,
    uplo: str = "F",
    verbose: bool = False,
    count_only: bool = False,
) -> FeastResult:
    """All eigenvalues of a dense Hermitian problem inside [emin, emax].

    A real-symmetric A dispatches to dfeast_sy{ev,gv}; a complex-Hermitian A to
    zfeast_he{ev,gv}. Passing B solves the generalized problem A x = lambda B x,
    which requires B positive definite.

    m0 is the subspace size -- an *over-estimate* of how many eigenvalues are in
    the interval. Too small returns info=3; we default to a generous guess.
    """
    A = np.asarray(A)
    if A.ndim != 2 or A.shape[0] != A.shape[1]:
        raise ValueError(f"A must be square, got shape {A.shape}")
    if emin >= emax:
        raise ValueError(f"need emin < emax, got emin={emin}, emax={emax}")

    n = A.shape[0]
    complex_problem = np.iscomplexobj(A) or (B is not None and np.iscomplexobj(B))
    dtype = np.complex128 if complex_problem else np.float64

    # FEAST is Fortran: column-major, and it reads A in place.
    A = np.asfortranarray(A, dtype=dtype)
    if B is not None:
        B = np.asfortranarray(np.asarray(B), dtype=dtype)
        if B.shape != A.shape:
            raise ValueError(f"B shape {B.shape} does not match A shape {A.shape}")

    if m0 is None:
        m0 = min(n, max(10, n // 4))
    m0 = int(min(m0, n))

    fpm = _make_fpm(contour_points, tol_exponent, max_loops, verbose, count_only)

    lam = np.zeros(m0, dtype=np.float64)             # eigenvalues are always real
    q = np.zeros((n, m0), dtype=dtype, order="F")
    res = np.zeros(m0, dtype=np.float64)

    epsout = _d(0.0)
    loop = _i(0)
    mode = _i(0)
    info = _i(0)
    n_c, lda, m0_c = _i(n), _i(n), _i(m0)
    emin_c, emax_c = _d(emin), _d(emax)
    uplo_c = ctypes.c_char(uplo.encode()[:1])

    prefix = "z" if complex_problem else "d"
    kind = "he" if complex_problem else "sy"
    name = f"{prefix}feast_{kind}{'gv' if B is not None else 'ev'}"
    fn = _lib.sym(name)

    args = [ctypes.byref(uplo_c), ctypes.byref(n_c), A.ctypes.data_as(ctypes.c_void_p),
            ctypes.byref(lda)]
    if B is not None:
        args += [B.ctypes.data_as(ctypes.c_void_p), ctypes.byref(lda)]
    args += [
        fpm.ctypes.data_as(ctypes.POINTER(_i)),
        ctypes.byref(epsout), ctypes.byref(loop),
        ctypes.byref(emin_c), ctypes.byref(emax_c),
        ctypes.byref(m0_c),
        lam.ctypes.data_as(ctypes.c_void_p),
        q.ctypes.data_as(ctypes.c_void_p),
        ctypes.byref(mode),
        res.ctypes.data_as(ctypes.c_void_p),
        ctypes.byref(info),
    ]
    fn(*args)

    m = max(0, mode.value)
    return FeastResult(
        eigenvalues=lam[:m].copy(),
        eigenvectors=q[:, :m].copy(),
        residuals=res[:m].copy(),
        n_found=m,
        loops=loop.value,
        epsout=epsout.value,
        info=info.value,
        subspace_used=m0,
    )


def spectral_bounds(A, B=None) -> tuple[float, float]:
    """Bracket the whole spectrum of a Hermitian A using Gershgorin discs.

    Every eigenvalue is guaranteed to lie in [lo, hi]. It costs one pass over
    the nonzeros -- no factorisation, no iteration -- which is what makes it
    usable for "show me the range" the instant a matrix is loaded.

    The bound is loose (often several times wider than the true spectrum), so
    treat it as the axis limits to explore within, not as an answer.

    For a generalized problem the discs bound A alone; the pencil's spectrum is
    scaled by B, so the range is widened by B's own Gershgorin extremes.
    """
    import scipy.sparse as sp

    def _discs(M):
        if sp.issparse(M):
            M = sp.csr_matrix(M)
            diag = np.real(M.diagonal())
            absM = abs(M)
            radius = np.asarray(absM.sum(axis=1)).ravel() - abs(diag)
        else:
            M = np.asarray(M)
            diag = np.real(np.diag(M))
            radius = np.abs(M).sum(axis=1) - np.abs(diag)
        return float(np.min(diag - radius)), float(np.max(diag + radius))

    lo, hi = _discs(A)

    if B is not None:
        # For spd B, lambda = (x'Ax/x'x) / (x'Bx/x'x), so the pencil's range is
        # bounded by the extreme ratios of A's range to B's range.
        #
        # B's *Gershgorin* lower bound is useless here: it is routinely <= 0
        # even for an spd B, and dividing by it produced ranges like 1e282.
        # So get B's actual extremes iteratively -- it is a plain symmetric
        # problem, no factorisation needed.
        import scipy.sparse.linalg as spla
        try:
            blo = float(spla.eigsh(B, k=1, which="SA", return_eigenvectors=False,
                                   tol=1e-4)[0])
            bhi = float(spla.eigsh(B, k=1, which="LA", return_eigenvectors=False,
                                   tol=1e-4)[0])
        except Exception as exc:
            raise RuntimeError(
                "could not bound the spectrum of B: " + str(exc)) from exc

        if blo <= 0:
            raise RuntimeError(
                f"B is not positive definite (smallest eigenvalue ~ {blo:.3g}); "
                "the generalized problem is not defined for it")

        ratios = [a / b for a in (lo, hi) for b in (blo, bhi)]
        lo, hi = min(ratios), max(ratios)

    if lo == hi:                      # degenerate (e.g. a multiple of identity)
        pad = max(abs(lo) * 1e-6, 1e-12)
        lo, hi = lo - pad, hi + pad
    return lo, hi


def estimate_count(A, emin: float, emax: float, B=None, *,
                   contour_points: int = 8, m0: Optional[int] = None) -> int:
    """Estimate how many eigenvalues lie in [emin, emax] without solving.

    Uses FEAST's built-in stochastic estimator (fpm(14)=2), which runs a single
    contour pass over random vectors. Far cheaper than a full solve, and it is
    what turns "guess M0 and retry" into a decision the app can make itself.

    The result is stochastic: expect it to be close, not exact. Size M0 above
    it, not equal to it.
    """
    import scipy.sparse as sp
    fn = eigsh_interval if sp.issparse(A) else eigh_interval
    r = fn(A, emin, emax, B, m0=m0, contour_points=contour_points,
           count_only=True)
    return max(0, r.n_found)


def _as_uplo(M, uplo: str):
    """Store M the way FEAST's UPLO argument says it is stored."""
    import scipy.sparse as sp
    if uplo == "U":
        return sp.triu(M, format="csr")
    if uplo == "L":
        return sp.tril(M, format="csr")
    return sp.csr_matrix(M)          # 'F': the whole matrix, untouched


def eigsh_interval(
    A,
    emin: float,
    emax: float,
    B=None,
    *,
    m0: Optional[int] = None,
    contour_points: int = 8,
    tol_exponent: int = 12,
    max_loops: int = 20,
    uplo: str = "U",
    verbose: bool = False,
    count_only: bool = False,
) -> FeastResult:
    """Sparse (CSR) real-symmetric version of :func:`eigh_interval`.

    Uses the IFEAST routines (difeast_scsr*), which solve the inner linear
    systems iteratively. The direct routines (dfeast_scsr*) need MKL-PARDISO,
    which is absent from an MKL=no build -- so these are the portable choice.
    """
    import scipy.sparse as sp

    A = sp.csr_matrix(A)
    n = A.shape[0]
    if A.shape[0] != A.shape[1]:
        raise ValueError(f"A must be square, got shape {A.shape}")
    if emin >= emax:
        raise ValueError(f"need emin < emax, got emin={emin}, emax={emax}")

    # FEAST wants 1-based CSR, stored to match UPLO: 'U'/'L' expect only that
    # triangle, 'F' expects the whole matrix. Triangularising an 'F' matrix
    # silently discards half of it and the solve then finds nothing.
    uplo = uplo.upper()
    if uplo not in ("U", "L", "F"):
        raise ValueError(f"uplo must be 'U', 'L' or 'F', got {uplo!r}")
    A = _as_uplo(A, uplo)
    A.sort_indices()
    sa = np.ascontiguousarray(A.data, dtype=np.float64)
    isa = np.ascontiguousarray(A.indptr + 1, dtype=np.int32)
    jsa = np.ascontiguousarray(A.indices + 1, dtype=np.int32)

    if B is not None:
        B = _as_uplo(sp.csr_matrix(B), uplo)
        B.sort_indices()
        sb = np.ascontiguousarray(B.data, dtype=np.float64)
        isb = np.ascontiguousarray(B.indptr + 1, dtype=np.int32)
        jsb = np.ascontiguousarray(B.indices + 1, dtype=np.int32)

    if m0 is None:
        m0 = min(n, max(10, n // 4))
    m0 = int(min(m0, n))

    fpm = _make_fpm(contour_points, tol_exponent, max_loops, verbose, count_only)

    lam = np.zeros(m0, dtype=np.float64)
    q = np.zeros((n, m0), dtype=np.float64, order="F")
    res = np.zeros(m0, dtype=np.float64)

    epsout, loop, mode, info = _d(0.0), _i(0), _i(0), _i(0)
    n_c, m0_c = _i(n), _i(m0)
    emin_c, emax_c = _d(emin), _d(emax)
    uplo_c = ctypes.c_char(uplo.upper().encode()[:1])

    name = "difeast_scsrgv" if B is not None else "difeast_scsrev"
    fn = _lib.sym(name)

    args = [ctypes.byref(uplo_c), ctypes.byref(n_c),
            sa.ctypes.data_as(ctypes.c_void_p),
            isa.ctypes.data_as(ctypes.POINTER(_i)),
            jsa.ctypes.data_as(ctypes.POINTER(_i))]
    if B is not None:
        args += [sb.ctypes.data_as(ctypes.c_void_p),
                 isb.ctypes.data_as(ctypes.POINTER(_i)),
                 jsb.ctypes.data_as(ctypes.POINTER(_i))]
    args += [
        fpm.ctypes.data_as(ctypes.POINTER(_i)),
        ctypes.byref(epsout), ctypes.byref(loop),
        ctypes.byref(emin_c), ctypes.byref(emax_c),
        ctypes.byref(m0_c),
        lam.ctypes.data_as(ctypes.c_void_p),
        q.ctypes.data_as(ctypes.c_void_p),
        ctypes.byref(mode),
        res.ctypes.data_as(ctypes.c_void_p),
        ctypes.byref(info),
    ]
    fn(*args)

    m = max(0, mode.value)
    return FeastResult(
        eigenvalues=lam[:m].copy(),
        eigenvectors=q[:, :m].copy(),
        residuals=res[:m].copy(),
        n_found=m,
        loops=loop.value,
        epsout=epsout.value,
        info=info.value,
        subspace_used=m0,
    )
