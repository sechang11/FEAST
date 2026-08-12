"""The problems FEAST 4.0 ships with, as a catalogue the GUI can browse.

Upstream distributes its test problems in two places and neither is loadable
without knowing things that live outside the matrix file:

  4.0/utility/data      12 named problems, each a .mtx plus a .in settings file
                        read by driver_feast_sparse.f90
  4.0/example/FEAST     36 programs -- 18 problems written twice, in C and F90 --
                        whose settings are compiled into the source

The .mtx files mostly carry no Matrix Market banner (only bcsstk11 does), so
nothing in the file says whether it is symmetric, whether only one triangle is
stored, or whether the values are real or complex. That information is in the
.in file, in the example source, or nowhere. This module is where we write it
down once, so a user picks a name instead of assembling seven facts by hand.

Every entry here was read off the .in files and the example sources, not
guessed; the sizes come from the .mtx headers.

    from feastpy import problems
    p = problems.get("helloworld")
    A, B = problems.load(p)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import sys


def _dirs():
    """Where the matrices live, in the source tree and in a frozen bundle.

    A packaged app has no source tree above the package, so the copies the
    PyInstaller spec bundles are checked first. Without this the catalogue
    resolves to paths that do not exist inside the .exe and every built-in
    problem silently disappears from the menu.
    """
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        for cand in (base / "feast_data", base / "4.0" / "utility" / "data"):
            if cand.is_dir():
                return cand, cand
    root = Path(__file__).resolve().parents[2] / "4.0"
    return root / "utility" / "data", root / "example" / "FEAST"


DATA, EXAMPLES = _dirs()

# How the .in file's first three lines map onto what the maths actually is.
# 's'+'d' real symmetric, 's'+'z' complex symmetric, 'h' Hermitian, 'g' general.
# The distinction matters because it decides the search geometry: real
# eigenvalues get an interval, complex ones need a disc.
INTERVAL = "interval"
DISC = "disc"

REAL_SYM = "real symmetric"
HERMITIAN = "complex Hermitian"
COMPLEX_SYM = "complex symmetric"
GENERAL = "general (non-Hermitian)"

# Which of these the GUI can actually solve today, and with what.
SOLVABLE = {REAL_SYM: "eigsh_interval", HERMITIAN: "eigsh_interval",
            GENERAL: "eig_disc", COMPLEX_SYM: "eig_disc"}


@dataclass(frozen=True)
class Problem:
    id: str
    title: str
    group: str
    symmetry: str
    kind: str                    # "standard" or "generalized"
    geometry: str                # INTERVAL or DISC
    uplo: str                    # from the .in file -- the only reliable signal
    m0: int
    n: int
    nnz: int
    about: str
    a_file: Optional[str] = None
    b_file: Optional[str] = None
    emin: Optional[float] = None
    emax: Optional[float] = None
    emid: Optional[complex] = None
    radius: Optional[float] = None
    programs: tuple = ()
    note: str = ""
    # Measured on an MKL-free build (BiCGStab inner solver, no PARDISO), which
    # is what we ship on all three platforms. Empty means it solves cleanly at
    # the settings above. Anything else is a warning the GUI shows up front,
    # because a built-in example that quietly returns nothing is worse than one
    # that says why.
    caveat: str = ""

    @property
    def generalized(self) -> bool:
        return self.kind == "generalized"

    @property
    def complex_valued(self) -> bool:
        return self.symmetry in (HERMITIAN, COMPLEX_SYM)

    @property
    def solver(self) -> Optional[str]:
        return SOLVABLE.get(self.symmetry)

    @property
    def search_text(self) -> str:
        if self.geometry == INTERVAL:
            return f"[{self.emin:g}, {self.emax:g}]"
        return f"disc centre {self.emid:g}, radius {self.radius:g}"


def _d(path: str) -> str:
    return str(DATA / path)


def _x(path: str) -> str:
    return str(EXAMPLES / path)


# --------------------------------------------------------------------- the 12
# Settings transcribed from 4.0/utility/data/*.in. These are the problems the
# original Linux driver is meant to be run on, and the README table is the
# source for the symmetry/standard/generalized columns.
_DATA_PROBLEMS = [
    Problem(
        id="helloworld", title="Hello world (4x4)", group="FEAST samples",
        symmetry=REAL_SYM, kind="standard", geometry=INTERVAL, uplo="L",
        emin=3.0, emax=5.0, m0=3, n=4, nnz=9,
        a_file=_d("helloworld.mtx"),
        about="The 4x4 matrix from section 2.4 of the user guide. Small enough "
              "to check by hand, which is exactly what it is for.",
        note="Both eigenvalues in [3,5] sit at exactly 4.0 -- a degenerate "
             "pair, which FEAST captures without special handling. "
             "helloworld.in ships M0=2; since M0 must exceed M, that returns "
             "info=3 and a residual of 2e-08. M0=3 converges to 3e-14, and is "
             "the subspace size the guide's own transcript shows."),
    Problem(
        id="system1", title="system1 - real symmetric, generalized",
        group="FEAST samples", symmetry=REAL_SYM, kind="generalized",
        geometry=INTERVAL, uplo="F", emin=0.18, emax=1.00, m0=30,
        n=1671, nnz=11435, a_file=_d("system1.mtx"), b_file=_d("system1B.mtx"),
        about="A generalized problem A x = lambda B x with both matrices stored "
              "in full. The standard worked example in the guide.",
        programs=("F90sparse_dfeast_scsrgv.f90", "Csparse_dfeast_scsrgv.c")),
    Problem(
        id="system2", title="system2 - complex Hermitian, standard",
        group="FEAST samples", symmetry=HERMITIAN, kind="standard",
        geometry=INTERVAL, uplo="F", emin=-0.35, emax=0.23, m0=40,
        n=600, nnz=2988, a_file=_d("system2.mtx"),
        about="Complex Hermitian. Its eigenvalues are still real, so the search "
              "is an interval -- but the arithmetic is complex throughout.",
        programs=("F90sparse_zfeast_hcsrev.f90", "Csparse_zfeast_hcsrev.c")),
    Problem(
        id="system3", title="system3 - general non-Hermitian, generalized",
        group="FEAST samples", symmetry=GENERAL, kind="generalized",
        geometry=DISC, uplo="F", emid=complex(0.59, 0.0001), radius=0.41, m0=30,
        n=1671, nnz=13011, a_file=_d("system3.mtx"), b_file=_d("system3B.mtx"),
        about="Non-Hermitian, so the eigenvalues are scattered in the complex "
              "plane and the search region is a disc rather than an interval.",
        programs=("F90sparse_dfeast_gcsrgv.f90", "Csparse_dfeast_gcsrgv.c"),
        note="The centre sits 1e-4 off the real axis on purpose: exactly on it, "
             "a real matrix's conjugate pairs straddle the contour."),
    Problem(
        id="system4", title="system4 - complex symmetric, standard",
        group="FEAST samples", symmetry=COMPLEX_SYM, kind="standard",
        geometry=DISC, uplo="F", emid=complex(4.0, 0.0), radius=3.0, m0=20,
        n=801, nnz=24591, a_file=_d("system4.mtx"),
        about="Complex symmetric (A = A^T, not A = A^H). Unlike Hermitian, its "
              "eigenvalues are complex, so it needs a disc.",
        programs=("F90sparse_zfeast_scsrev.f90", "Csparse_zfeast_scsrev.c")),

    # ---- real applications ------------------------------------------------
    Problem(
        id="cnt", title="Carbon nanotube", group="Real-world problems",
        symmetry=REAL_SYM, kind="generalized", geometry=INTERVAL, uplo="F",
        emin=-65.0, emax=4.96, m0=150, n=12450, nnz=86808,
        a_file=_d("cnt.mtx"), b_file=_d("cntB.mtx"),
        about="Electronic structure of a carbon nanotube. The interval spans "
              "most of the occupied states, so this one asks for a lot at once.",
        caveat="Slow but correct: 100 eigenvalues, 21 loops, residual 3.5e-13 "
               "in about 2.5 minutes here.",
        note="cnt.in has a stray extra token on the M0 line ('150 0') that "
             "Fortran's list-directed read ignores."),
    Problem(
        id="co", title="Carbon monoxide", group="Real-world problems",
        symmetry=REAL_SYM, kind="generalized", geometry=INTERVAL, uplo="L",
        emin=-700.0, emax=-0.5, m0=20, n=8478, nnz=123834,
        a_file=_d("co.mtx"), b_file=_d("coB.mtx"),
        about="A CO molecule from quantum chemistry. Only the lower triangle is "
              "stored, which is why uplo is 'L'.",
        caveat="Does not converge at the shipped settings: M0=20 over the "
               "interval [-700, -0.5] runs the full 50 loops and stops at "
               "info=2 with a residual of 1.2e-03 (9 eigenvalues, 26s). The "
               "subspace is too small for the interval -- raise M0."),
    Problem(
        id="c6h6", title="Benzene (C6H6)", group="Real-world problems",
        symmetry=REAL_SYM, kind="generalized", geometry=INTERVAL, uplo="L",
        emin=-300.0, emax=-0.45, m0=50, n=49192, nnz=727870,
        a_file=_d("c6h6.mtx"), b_file=_d("c6h6B.mtx"),
        about="A benzene molecule, and the largest problem shipped: n = 49,192. "
              "Realistic quantum chemistry, and slow without a direct solver.",
        caveat="Returns info=1 (nothing found) at the shipped settings here: "
               "M0=50 over [-300, -0.45], 3 loops, 14s. The largest problem "
               "shipped and the one most in need of the direct solver an MKL "
               "build provides."),
    Problem(
        id="Na5", title="Sodium cluster (Na5)", group="Real-world problems",
        symmetry=REAL_SYM, kind="standard", geometry=INTERVAL, uplo="L",
        emin=-0.5, emax=1.26, m0=150, n=5832, nnz=155731,
        a_file=_d("Na5.mtx"),
        about="A five-atom sodium cluster. A standard problem, so no B matrix.",
        caveat="Takes about 40 seconds: 100 eigenvalues, residual 1.5e-13."),
    Problem(
        id="bcsstk11", title="Structural stiffness (bcsstk11)",
        group="Real-world problems", symmetry=REAL_SYM, kind="generalized",
        geometry=INTERVAL, uplo="L", emin=0.0, emax=3.85e7, m0=950,
        n=1473, nnz=17857, a_file=_d("bcsstk11.mtx"), b_file=_d("bcsstk11B.mtx"),
        about="A stiffness matrix from structural engineering (Harwell-Boeing). "
              "The eigenvalues are squared vibration frequencies, hence the "
              "enormous interval.",
        note="The only file here carrying a Matrix Market banner, so scipy "
             "mirrors it on load: 17,857 stored entries become 34,241 and the "
             "array is full even though the .in says UPLO='L'. That is why "
             "storage is read off the data, not the paperwork. Its B matrix "
             "is purely diagonal (a lumped mass matrix).",
        caveat="Correct but slow: 800 eigenvalues, 15 loops, residual 2.4e-13 "
               "in about 6 minutes here. M0=950 is a big subspace."),
    Problem(
        id="grcar", title="Grcar matrix", group="Real-world problems",
        symmetry=GENERAL, kind="standard", geometry=DISC, uplo="F",
        emid=complex(0.3, 2.0), radius=0.5, m0=25, n=100, nnz=493,
        a_file=_d("grcar.mtx"),
        about="A textbook non-normal matrix. Its eigenvalues are famously "
              "sensitive, which makes it a good stress test for a disc search.",
        caveat="Does not converge in this build. 19 eigenvalues really do lie "
               "in the disc, but the iterative inner solver returns info=1 "
               "(nothing found) at M0=25 and info=-2 (inner solver failed) at "
               "M0=40. dfeast_gcsrev and difeast_gcsrev behave identically, "
               "which is expected without MKL: there is no PARDISO in the "
               "shipped library, so both fall back to BiCGStab. Non-normal "
               "matrices are exactly where that struggles. Needs an MKL build."),
    Problem(
        id="qc324", title="Quantum chemistry (qc324)",
        group="Real-world problems", symmetry=COMPLEX_SYM, kind="standard",
        geometry=DISC, uplo="F", emid=complex(0.0, 0.0), radius=0.02, m0=50,
        n=324, nnz=26730, a_file=_d("qc324.mtx"),
        about="A dense-ish complex symmetric matrix (25% filled) with a very "
              "small search disc around the origin.",
        caveat="Slow here. All 17 eigenvalues in the disc are found at the .in "
               "settings, but they do not converge (info=2, residual 0.52). "
               "M0=80 with 32 contour points and 60 loops reaches 4e-12 in "
               "about two minutes. The disc radius is 0.02 against a spectrum "
               "spanning 2.0, so the filter has very little room to work."),
]

# ------------------------------------------------------- the example programs
# system5 is the polynomial example: three matrices A0 + lambda A1 + lambda^2 A2.
# The GUI cannot solve it yet -- it is listed so the catalogue matches what
# upstream ships rather than quietly omitting a whole family.
_EXAMPLE_ONLY = [
    Problem(
        id="system5", title="system5 - polynomial (quadratic)",
        group="Example programs", symmetry=REAL_SYM, kind="standard",
        geometry=DISC, uplo="F", emid=complex(-1.55, 0.0), radius=0.05, m0=20,
        n=1000, nnz=2998, a_file=_x("system5A0.mtx"),
        about="A quadratic eigenvalue problem: (A0 + lambda A1 + lambda^2 A2) x "
              "= 0. Arises with damping, where the eigenvalue appears squared.",
        programs=("F90sparse_dfeast_scsrpev.f90", "Csparse_dfeast_scsrpev.c"),
        note="Needs all three of system5A0/A1/A2. Not solvable from the GUI "
             "yet -- feastpy has no polynomial entry point."),
]

ALL: tuple = tuple(_DATA_PROBLEMS + _EXAMPLE_ONLY)
BY_ID = {p.id: p for p in ALL}


def get(problem_id: str) -> Problem:
    try:
        return BY_ID[problem_id]
    except KeyError:
        raise KeyError(f"no such built-in problem: {problem_id!r}. "
                       f"Available: {', '.join(sorted(BY_ID))}") from None


def groups() -> dict:
    """Problems arranged for a browser, preserving the order defined above."""
    out: dict = {}
    for p in ALL:
        out.setdefault(p.group, []).append(p)
    return out


def available(p: Problem) -> bool:
    """Is the matrix data actually on disk? Absent for a source-only checkout."""
    if not p.a_file or not Path(p.a_file).is_file():
        return False
    return not (p.b_file and not Path(p.b_file).is_file())


def effective_uplo(A, declared: str) -> str:
    """What `uplo` actually describes the array in memory.

    The .in file's UPLO describes the *file*, and for most of these that is
    also what lands in memory. bcsstk11 is the exception: it is the one file
    with a Matrix Market banner, so scipy.io.mmread honours `symmetric` and
    mirrors it, turning 17857 stored entries into 34241. Its .in still says
    'L'. Passing a mirrored matrix to FEAST while claiming one triangle makes
    it count every off-diagonal entry twice, which is a wrong answer with no
    error, so trust the array rather than the paperwork.
    """
    import scipy.sparse as sp

    A = sp.csr_matrix(A)
    if A.nnz == 0:
        return declared
    upper = (sp.triu(A, k=1).nnz > 0)
    lower = (sp.tril(A, k=-1).nnz > 0)
    if upper and lower:
        return "F"
    if upper:
        return "U"
    if lower:
        return "L"
    return declared          # diagonal only -- any convention is correct


def load(p: Problem):
    """Return (A, B) as SciPy CSR, B being None for a standard problem.

    Two normalisations happen here, and both exist because the shipped files
    disagree with their own settings files:

    * Values are downcast to real when the problem is declared real and every
      imaginary part is zero. Most of these .mtx files use the four-column
      complex layout regardless -- grcar.in says 'd' (double real) but
      grcar.mtx stores `i j re im`. Left complex, it would be routed to a
      complex routine for no reason.
    * The storage triangle is NOT changed. Call `effective_uplo` to find out
      what to tell FEAST; mirroring here would double-count off-diagonals.
    """
    import numpy as np

    from . import matrixio

    def _load(path):
        M = matrixio.load_matrix(path)
        if M is not None and M.dtype.kind == "c" and not p.complex_valued:
            # count_nonzero, not max(): scipy's sparse max() has no `initial`
            # and raises on an all-zero matrix.
            if M.imag.count_nonzero() == 0:
                M = M.real.astype(np.float64)
        return M

    A = _load(p.a_file)
    B = _load(p.b_file) if p.b_file else None
    return A, B
