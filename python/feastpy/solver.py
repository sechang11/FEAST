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
    # Set by eig_disc: the general (non-Hermitian) interfaces return left
    # eigenvectors as well, and it helps to know which routine ran.
    left_eigenvectors: Optional[np.ndarray] = None
    routine: str = ""
    # All M0 subspace slots, not just the M accepted ones, plus the parameter
    # array FEAST returned. fpm carries output slots too -- fpm(30) says which
    # routine actually ran and fpm(60) counts inner BiCGStab iterations -- so
    # without it there is no way to report what really happened.
    all_eigenvalues: Optional[np.ndarray] = None
    all_residuals: Optional[np.ndarray] = None
    fpm: Optional[np.ndarray] = None

    @property
    def converged(self) -> bool:
        return self.info == 0

    @property
    def message(self) -> str:
        return explain_info(self.info)


def _make_fpm(contour_points: Optional[int], tol_exponent: Optional[int],
              max_loops: Optional[int], verbose: bool,
              count_only: bool = False, rule: Optional[int] = None,
              ratio: Optional[int] = None) -> np.ndarray:
    """fpm is FEAST's 64-entry parameter array.

    Note the index shift: the documentation uses Fortran's fpm(1..64), so
    fpm(N) is fpm[N-1] here.

    feastinit does NOT fill in defaults -- it sets all 64 slots to -111, which
    means "the user did not choose; let the routine decide". Each routine then
    substitutes a default appropriate to itself, and those differ: the guide
    gives 8 contour points for FEAST but 4 for IFEAST, and 20 refinement loops
    for FEAST but 50 for IFEAST.

    So writing a value here is not "setting the default", it is overriding the
    routine's judgement. Doing that unconditionally forced 20 loops onto the
    IFEAST routines these wrappers actually call, and system2 -- FEAST's own
    complex Hermitian sample -- then stopped at info=2 (no convergence) with a
    residual of 2.6e-06. Left alone it converges. Pass None to leave a slot at
    -111; only an explicit value is written.
    """
    fpm = np.zeros(64, dtype=np.int32)
    _lib.sym("feastinit")(fpm.ctypes.data_as(ctypes.POINTER(_i)))
    fpm[0] = 1 if verbose else 0     # fpm(1)  runtime printing
    if contour_points is not None:
        fpm[1] = contour_points      # fpm(2)  quadrature points on the contour
    if tol_exponent is not None:
        fpm[2] = tol_exponent        # fpm(3)  stop at 1e-<tol_exponent>
    if max_loops is not None:
        fpm[3] = max_loops           # fpm(4)  max refinement loops
    if rule is not None:
        fpm[15] = rule               # fpm(16) 0 Gauss, 1 Trapezoidal, 2 Zolotarev
    if ratio is not None:
        fpm[17] = ratio              # fpm(18) ellipse ratio x100
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
    contour_points: Optional[int] = None,
    tol_exponent: Optional[int] = None,
    max_loops: Optional[int] = None,
    uplo: str = "F",
    rule: Optional[int] = None,
    ratio: Optional[int] = None,
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

    fpm = _make_fpm(contour_points, tol_exponent, max_loops, verbose,
                    count_only, rule, ratio)

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
        routine=name,
        # FEAST fills all M0 slots; those past M hold the Ritz values it
        # examined and rejected as outside the interval. Truncating to M threw
        # away the evidence for whether the subspace was big enough, so keep it
        # alongside the headline answer rather than instead of it.
        all_eigenvalues=lam.copy(),
        all_residuals=res.copy(),
        fpm=fpm.copy(),
    )


def eig_disc(
    A,
    center: complex,
    radius: float,
    B=None,
    *,
    m0: Optional[int] = None,
    contour_points: int = 16,
    tol_exponent: Optional[int] = None,
    max_loops: Optional[int] = None,
    uplo: str = "F",
    verbose: bool = False,
) -> FeastResult:
    """Eigenvalues inside a disc of the complex plane.

    This is the non-Hermitian and complex-symmetric side of FEAST. Those
    spectra are not real, so there is no interval to search: the contour is a
    circle of `radius` about `center`, and the eigenvalues come back complex.

    Dispatches to:
      * ``zfeast_sy{ev,gv}`` / ``zfeast_scsr{ev,gv}``  complex *symmetric*
        (A == A.T, not conjugated -- a different problem from Hermitian)
      * ``dfeast_ge{ev,gv}`` / ``dfeast_gcsr{ev,gv}``  real non-symmetric
      * ``zfeast_ge{ev,gv}`` / ``zfeast_gcsr{ev,gv}``  complex general

    For general problems FEAST returns right *and* left eigenvectors: the
    result's ``eigenvectors`` holds the right ones and ``left_eigenvectors``
    the left ones. Residuals likewise come in pairs.
    """
    import scipy.sparse as sp

    sparse = sp.issparse(A)
    n = A.shape[0]
    if A.shape[0] != A.shape[1]:
        raise ValueError(f"A must be square, got shape {A.shape}")
    if radius <= 0:
        raise ValueError(f"radius must be positive, got {radius}")

    complex_in = np.iscomplexobj(A.data if sparse else A) or (
        B is not None and np.iscomplexobj(B.data if sp.issparse(B) else B))

    # Complex symmetric is its own interface; it is not Hermitian and not
    # general, and using the wrong one silently gives wrong answers.
    sym, herm = _symmetry(A)
    complex_symmetric = complex_in and sym and not herm

    if m0 is None:
        m0 = min(n, max(10, n // 4))
    m0 = int(min(m0, n))

    fpm = _make_fpm(contour_points, tol_exponent, max_loops, verbose)
    # A complex contour is a FULL contour, and its point count is fpm(8) --
    # fpm(2) is the half-contour count the Hermitian routines use and is
    # ignored here. Setting only fpm(2) made contour_points a silent no-op,
    # which showed up as a platform-dependent miss on a marginal problem.
    fpm[7] = int(contour_points)

    if complex_symmetric:
        prefix, kind, ncols = "z", "sy", 1
    else:
        prefix, kind, ncols = ("z" if complex_in else "d"), "ge", 2
    tail = "gv" if B is not None else "ev"
    name = (f"{prefix}feast_{kind}{tail}" if not sparse else
            f"{prefix}feast_{'s' if complex_symmetric else 'g'}csr{tail}")

    # The MATRIX dtype follows the routine prefix, not the result: dfeast_ge*
    # takes a real double* A even though its eigenvalues are complex. Passing a
    # complex array there makes FEAST read interleaved re/im pairs as
    # consecutive reals -- a garbled matrix that still "solves", just wrongly.
    mat_dtype = np.complex128 if prefix == "z" else np.float64
    dtype = np.complex128            # eigenvalues and eigenvectors are complex

    lam = np.zeros(m0, dtype=dtype)
    q = np.zeros((n, ncols * m0), dtype=dtype, order="F")
    res = np.zeros(ncols * m0, dtype=np.float64)

    emid = np.array([complex(center).real, complex(center).imag], dtype=np.float64)
    r_c = _d(float(radius))
    epsout, loop, mode, info = _d(0.0), _i(0), _i(0), _i(0)
    n_c, lda, m0_c = _i(n), _i(n), _i(m0)
    uplo_c = ctypes.c_char(uplo.upper().encode()[:1])

    args: list = []
    if complex_symmetric and not sparse:
        args.append(ctypes.byref(uplo_c))          # only the sy interfaces take UPLO
    args.append(ctypes.byref(n_c))

    if sparse:
        A = _as_uplo(sp.csr_matrix(A), uplo.upper() if complex_symmetric else "F")
        A.sort_indices()
        sa = np.ascontiguousarray(A.data, dtype=mat_dtype)
        isa = np.ascontiguousarray(A.indptr + 1, dtype=np.int32)
        jsa = np.ascontiguousarray(A.indices + 1, dtype=np.int32)
        if complex_symmetric:
            args.insert(0, ctypes.byref(uplo_c))
        args += [sa.ctypes.data_as(ctypes.c_void_p),
                 isa.ctypes.data_as(ctypes.POINTER(_i)),
                 jsa.ctypes.data_as(ctypes.POINTER(_i))]
        if B is not None:
            Bm = _as_uplo(sp.csr_matrix(B), uplo.upper() if complex_symmetric else "F")
            Bm.sort_indices()
            sb = np.ascontiguousarray(Bm.data, dtype=mat_dtype)
            isb = np.ascontiguousarray(Bm.indptr + 1, dtype=np.int32)
            jsb = np.ascontiguousarray(Bm.indices + 1, dtype=np.int32)
            args += [sb.ctypes.data_as(ctypes.c_void_p),
                     isb.ctypes.data_as(ctypes.POINTER(_i)),
                     jsb.ctypes.data_as(ctypes.POINTER(_i))]
    else:
        A = np.asfortranarray(A, dtype=mat_dtype)
        args += [A.ctypes.data_as(ctypes.c_void_p), ctypes.byref(lda)]
        if B is not None:
            B = np.asfortranarray(B, dtype=mat_dtype)
            args += [B.ctypes.data_as(ctypes.c_void_p), ctypes.byref(lda)]

    args += [
        fpm.ctypes.data_as(ctypes.POINTER(_i)),
        ctypes.byref(epsout), ctypes.byref(loop),
        emid.ctypes.data_as(ctypes.c_void_p), ctypes.byref(r_c),
        ctypes.byref(m0_c),
        lam.ctypes.data_as(ctypes.c_void_p),
        q.ctypes.data_as(ctypes.c_void_p),
        ctypes.byref(mode),
        res.ctypes.data_as(ctypes.c_void_p),
        ctypes.byref(info),
    ]
    _lib.sym(name)(*args)

    m = max(0, mode.value)
    right = q[:, :m].copy()
    left = q[:, m0:m0 + m].copy() if ncols == 2 else None
    out = FeastResult(
        eigenvalues=lam[:m].copy(),
        eigenvectors=right,
        residuals=res[:m].copy(),
        n_found=m,
        loops=loop.value,
        epsout=epsout.value,
        info=info.value,
        subspace_used=m0,
    )
    out.left_eigenvectors = left
    out.routine = name
    return out


def _symmetry(M, tol: float = 1e-10) -> tuple[bool, bool]:
    import scipy.sparse as sp
    if sp.issparse(M):
        d = abs(M - M.T)
        sym = (d.max() if d.nnz else 0.0) <= tol
        dh = abs(M - M.getH())
        herm = (dh.max() if dh.nnz else 0.0) <= tol
        return bool(sym), bool(herm)
    M = np.asarray(M)
    return (bool(np.allclose(M, M.T, atol=tol)),
            bool(np.allclose(M, M.conj().T, atol=tol)))


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
    contour_points: Optional[int] = None,
    tol_exponent: Optional[int] = None,
    max_loops: Optional[int] = None,
    uplo: str = "U",
    rule: Optional[int] = None,
    ratio: Optional[int] = None,
    verbose: bool = False,
    count_only: bool = False,
) -> FeastResult:
    """Sparse (CSR) Hermitian version of :func:`eigh_interval`.

    A real-symmetric A dispatches to difeast_scsr{ev,gv}; a complex-Hermitian A
    to zifeast_hcsr{ev,gv}. These are the IFEAST routines, which solve the inner
    linear systems iteratively; the direct routines (dfeast_scsr*) need
    MKL-PARDISO, absent from an MKL=no build, so these are the portable choice.

    Eigenvalues of a Hermitian matrix are real whatever the matrix is, so
    `eigenvalues` is real in both cases; only `eigenvectors` turns complex.
    """
    import scipy.sparse as sp

    A = sp.csr_matrix(A)
    # A complex matrix MUST NOT be handed to the real routines. Casting it
    # silently drops the imaginary part, and FEAST then solves a different
    # matrix and reports info=0 -- success, on the wrong problem. Measured on a
    # 40x40 complex Hermitian case: 2 eigenvalues returned instead of 5, none
    # within 0.65 of a true one, info=0 throughout.
    complex_problem = np.iscomplexobj(A.data) or (
        B is not None and np.iscomplexobj(sp.csr_matrix(B).data))
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
    # A full complex matrix that is not Hermitian has complex eigenvalues, so an
    # interval search is meaningless -- say so rather than returning nonsense.
    # Only checkable for uplo='F'; with one triangle stored we trust the
    # declaration, exactly as FEAST does.
    if complex_problem and uplo == "F":
        d = abs(A - A.getH()).max() if A.nnz else 0.0
        if d > 1e-10 * max(1.0, abs(A).max()):
            raise ValueError(
                f"A is complex but not Hermitian (max|A - A^H| = {d:.3e}). Its "
                "eigenvalues are not real, so an interval search cannot find "
                "them -- use eig_disc() to search a disc in the complex plane.")

    dtype = np.complex128 if complex_problem else np.float64

    A = _as_uplo(A, uplo)
    A.sort_indices()
    sa = np.ascontiguousarray(A.data, dtype=dtype)
    isa = np.ascontiguousarray(A.indptr + 1, dtype=np.int32)
    jsa = np.ascontiguousarray(A.indices + 1, dtype=np.int32)

    if B is not None:
        B = _as_uplo(sp.csr_matrix(B), uplo)
        B.sort_indices()
        sb = np.ascontiguousarray(B.data, dtype=dtype)
        isb = np.ascontiguousarray(B.indptr + 1, dtype=np.int32)
        jsb = np.ascontiguousarray(B.indices + 1, dtype=np.int32)

    if m0 is None:
        m0 = min(n, max(10, n // 4))
    m0 = int(min(m0, n))

    fpm = _make_fpm(contour_points, tol_exponent, max_loops, verbose,
                    count_only, rule, ratio)

    # Eigenvalues and residuals stay real -- a Hermitian matrix has real
    # eigenvalues -- but the eigenvectors follow the matrix.
    lam = np.zeros(m0, dtype=np.float64)
    q = np.zeros((n, m0), dtype=dtype, order="F")
    res = np.zeros(m0, dtype=np.float64)

    epsout, loop, mode, info = _d(0.0), _i(0), _i(0), _i(0)
    n_c, m0_c = _i(n), _i(m0)
    emin_c, emax_c = _d(emin), _d(emax)
    uplo_c = ctypes.c_char(uplo.upper().encode()[:1])

    if complex_problem:
        name = "zifeast_hcsrgv" if B is not None else "zifeast_hcsrev"
    else:
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
        routine=name,
        # FEAST fills all M0 slots; those past M hold the Ritz values it
        # examined and rejected as outside the interval. Truncating to M threw
        # away the evidence for whether the subspace was big enough, so keep it
        # alongside the headline answer rather than instead of it.
        all_eigenvalues=lam.copy(),
        all_residuals=res.copy(),
        fpm=fpm.copy(),
    )
