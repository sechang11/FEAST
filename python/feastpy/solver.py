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
              verbose: bool) -> np.ndarray:
    """fpm is FEAST's 64-entry parameter array; feastinit fills in the defaults."""
    fpm = np.zeros(64, dtype=np.int32)
    _lib.sym("feastinit")(fpm.ctypes.data_as(ctypes.POINTER(_i)))
    fpm[0] = 1 if verbose else 0     # runtime printing
    fpm[1] = contour_points          # quadrature points on the contour
    fpm[2] = tol_exponent            # stop at 1e-<tol_exponent>
    fpm[3] = max_loops               # max refinement loops
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

    fpm = _make_fpm(contour_points, tol_exponent, max_loops, verbose)

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

    # FEAST wants upper-triangle CSR with 1-based indices.
    A = sp.triu(A, format="csr") if uplo.upper() == "U" else sp.tril(A, format="csr")
    A.sort_indices()
    sa = np.ascontiguousarray(A.data, dtype=np.float64)
    isa = np.ascontiguousarray(A.indptr + 1, dtype=np.int32)
    jsa = np.ascontiguousarray(A.indices + 1, dtype=np.int32)

    if B is not None:
        B = sp.csr_matrix(B)
        B = sp.triu(B, format="csr") if uplo.upper() == "U" else sp.tril(B, format="csr")
        B.sort_indices()
        sb = np.ascontiguousarray(B.data, dtype=np.float64)
        isb = np.ascontiguousarray(B.indptr + 1, dtype=np.int32)
        jsb = np.ascontiguousarray(B.indices + 1, dtype=np.int32)

    if m0 is None:
        m0 = min(n, max(10, n // 4))
    m0 = int(min(m0, n))

    fpm = _make_fpm(contour_points, tol_exponent, max_loops, verbose)

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
