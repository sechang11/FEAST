"""Loading matrices from the formats users actually have on disk."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import numpy as np
import scipy.io
import scipy.sparse as sp


class MatrixLoadError(ValueError):
    pass


SUPPORTED = ("Matrix Market (*.mtx *.mtx.gz);;CSV (*.csv *.txt);;"
             "NumPy (*.npy *.npz);;CSR arrays (*.csr *.txt *.dat);;"
             "All files (*)")


def load_matrix(path: str | Path):
    """Return a dense ndarray or a scipy sparse matrix, whichever fits the file.

    Matrix Market is the lingua franca for sparse test matrices (and what the
    SuiteSparse collection ships), so it is the primary path.
    """
    path = Path(path)
    if not path.exists():
        raise MatrixLoadError(f"file not found: {path}")

    suf = path.suffixes
    try:
        if ".mtx" in suf:
            try:
                m = scipy.io.mmread(str(path))
            except ValueError:
                # FEAST's own data files in 4.0/utility/data are a mix: some
                # carry the %%MatrixMarket banner, some are bare coordinate
                # format ("nrow ncol nnz" then i j value). Without this fallback
                # the app cannot open the matrices FEAST itself ships.
                m = _read_bare_coordinate(path)
            return sp.csr_matrix(m) if sp.issparse(m) else np.asarray(m)
        if ".npy" in suf:
            return np.load(str(path))
        if ".npz" in suf:
            try:
                return sp.load_npz(str(path))
            except Exception:
                data = np.load(str(path))
                return data[list(data.keys())[0]]
        # Fall through to delimited text; sniff the separator.
        text = path.read_text().strip()
        # ...but decide coordinate-vs-dense from the content, not the name.
        # Coordinate files are not always called .mtx -- .dat and .txt are
        # common -- and read as dense they become the triplet table itself:
        # "2 2 2 / 1 1 5.0 / 2 2 7.0" loaded as a 3x3 of indices, which is
        # square, passes every downstream guard, and gets solved. A wrong
        # matrix with no error is worse than a refusal.
        if _looks_like_coordinate(text):
            return _read_bare_coordinate(path)
        delim = "," if "," in text.splitlines()[0] else None
        return np.loadtxt(str(path), delimiter=delim)
    except MatrixLoadError:
        raise
    except Exception as exc:
        raise MatrixLoadError(f"could not read {path.name}: {exc}") from exc


def _looks_like_coordinate(text: str) -> bool:
    """Is this banner-less coordinate format rather than a dense table?

    The test is the header's own claim: a coordinate file opens with
    "nrow ncol nnz", and nnz must equal the number of data lines that follow.
    Requiring that agreement is what keeps it from firing on a genuine dense
    3-column table, where the first row is data and the count would only match
    by coincidence.

    Deliberately strict. Guessing wrong in this direction turns a dense matrix
    into a sparse one built from its own first row, which is the same class of
    silent error this is here to prevent.
    """
    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln and not ln.startswith(("%", "#", "!"))]
    if len(lines) < 2:
        return False
    head = lines[0].split()
    if len(head) != 3:
        return False
    try:
        nrow, ncol, nnz = (int(x) for x in head)
    except ValueError:
        return False                      # a float in the header: dense data
    if nrow <= 0 or ncol <= 0 or nnz < 0 or nnz != len(lines) - 1:
        return False
    # Every data line must start with a plausible 1-based index pair.
    for ln in lines[1:]:
        parts = ln.split()
        if len(parts) < 3:
            return False
        try:
            i, j = int(parts[0]), int(parts[1])
        except ValueError:
            return False
        if not (1 <= i <= nrow and 1 <= j <= ncol):
            return False
    return True


def _read_bare_coordinate(path: Path):
    """Read banner-less coordinate format: 'nrow ncol nnz' then i j value lines.

    Fortran writes doubles as 1.0D-19; Python needs 1.0e-19.
    """
    rows, cols, vals = [], [], []
    n = m = None
    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith(("%", "#", "!")):
                continue
            parts = line.replace("D", "e").replace("d", "e").split()
            if n is None:
                if len(parts) < 3:
                    raise MatrixLoadError(f"{path.name}: bad header line {line!r}")
                n, m = int(parts[0]), int(parts[1])
                continue
            if len(parts) < 3:
                continue
            rows.append(int(parts[0]) - 1)          # 1-based on disk
            cols.append(int(parts[1]) - 1)
            if len(parts) >= 4:                      # complex: i j re im
                vals.append(complex(float(parts[2]), float(parts[3])))
            else:
                vals.append(float(parts[2]))

    if n is None:
        raise MatrixLoadError(f"{path.name}: no data found")
    dtype = complex if any(isinstance(v, complex) for v in vals) else float
    return sp.coo_matrix((np.array(vals, dtype=dtype), (rows, cols)),
                         shape=(n, m)).tocsr()


def read_csr_arrays(*sources, n: Optional[int] = None):
    """Build a matrix from FEAST's own three CSR arrays: sa, ja, ia.

    This is the form the C and Fortran interfaces take directly --

        dfeast_scsrev(&uplo, &n, sa, isa, jsa, fpm, ...)

    -- so anyone already calling FEAST from their own code has the matrix in
    exactly these arrays and no reason to convert it to coordinate format
    first.

    Accepts either one file holding all three arrays in order (sa, then ja,
    then ia; any whitespace or line arrangement) or three files given in that
    order. An optional leading "n nnz" or "n n nnz" header is consumed if
    present, but nothing depends on it.

    There is no standard file layout for a CSR triple, and the two plausible
    index bases -- 0 from SciPy, 1 from Fortran -- describe *different
    matrices* from identical digits. Guessing would be the worst kind of bug
    this project can ship, so nothing is guessed: the row-pointer array is
    self-describing and everything is derived from it.

      * ia has n+1 entries, is non-decreasing, starts at the base and ends at
        base + nnz
      * sa and ja both have exactly nnz entries
      * every column index lies inside [base, base + ncols)

    A layout that does not satisfy all of that is refused with the reason,
    rather than loaded as something else. When the split is ambiguous -- more
    than one (n, base) fits the token count -- that is also a refusal.
    """
    import numpy as np
    import scipy.sparse as sp

    texts = []
    for s in sources:
        p = Path(s)
        if not p.exists():
            raise MatrixLoadError(f"file not found: {p}")
        texts.append(p.read_text())

    if len(texts) == 3:
        sa = _tokens(texts[0], "sa (values)")
        ja = _tokens(texts[1], "ja (column indices)")
        ia = _tokens(texts[2], "ia (row pointers)")
        return _assemble_csr(sa, ja, ia, n=n)

    if len(texts) != 1:
        raise MatrixLoadError(
            "give either one file containing sa, ja and ia in that order, "
            f"or three files in that order; got {len(texts)}")

    toks = _tokens(texts[0], "the CSR file")

    # An explicit header removes all ambiguity, so use it when it is there.
    head = [ln for ln in texts[0].splitlines() if ln.strip()
            and not ln.strip().startswith(("%", "#", "!"))]
    if head:
        first = head[0].split()
        if len(first) in (2, 3) and all(_is_int(x) for x in first):
            declared_n = int(first[0])
            declared_nnz = int(first[-1])
            rest = toks[len(first):]
            if len(rest) == 2 * declared_nnz + declared_n + 1:
                return _assemble_csr(rest[:declared_nnz],
                                     rest[declared_nnz:2 * declared_nnz],
                                     rest[2 * declared_nnz:], n=declared_n)

    # No usable header: recover the split from the pointer array's shape.
    # For an n-row matrix the file holds nnz + nnz + (n+1) numbers, and the
    # trailing n+1 of them must be a valid pointer array. Only accept a split
    # that is unique.
    total = len(toks)
    fits = []
    for rows in range(1, total):
        nnz2 = total - rows - 1
        if nnz2 < 0 or nnz2 % 2:
            continue
        nnz = nnz2 // 2
        tail = toks[2 * nnz:]
        if len(tail) != rows + 1:
            continue
        try:
            _validate_pointers(tail, nnz)
        except MatrixLoadError:
            continue
        fits.append((rows, nnz))

    if not fits:
        raise MatrixLoadError(
            "this does not look like sa/ja/ia: no split of the "
            f"{total} numbers leaves a valid row-pointer array. A CSR file "
            "should hold nnz values, then nnz column indices, then n+1 row "
            "pointers.")
    if len(fits) > 1:
        shapes = ", ".join(f"n={r} nnz={z}" for r, z in fits[:3])
        raise MatrixLoadError(
            f"ambiguous CSR file: {len(fits)} different shapes fit these "
            f"numbers ({shapes}...). Add a header line 'n nnz', or supply "
            "sa, ja and ia as three separate files.")

    rows, nnz = fits[0]
    return _assemble_csr(toks[:nnz], toks[nnz:2 * nnz], toks[2 * nnz:], n=rows)


def _is_int(tok: str) -> bool:
    try:
        int(tok)
        return True
    except ValueError:
        return False


def _tokens(text: str, what: str) -> list:
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("%", "#", "!")):
            continue
        for tok in line.replace("D", "e").replace("d", "e").split():
            try:
                out.append(float(tok))
            except ValueError:
                raise MatrixLoadError(
                    f"{what}: {tok!r} is not a number") from None
    if not out:
        raise MatrixLoadError(f"{what}: no numbers found")
    return out


def _validate_pointers(ia, nnz: int):
    """ia must be non-decreasing integers spanning exactly nnz entries."""
    if any(abs(v - round(v)) > 1e-9 for v in ia):
        raise MatrixLoadError("row pointers must be integers")
    vals = [int(round(v)) for v in ia]
    base = vals[0]
    if base not in (0, 1):
        raise MatrixLoadError(
            f"row pointers must start at 0 or 1, they start at {base}")
    if any(b < a for a, b in zip(vals, vals[1:])):
        raise MatrixLoadError("row pointers must be non-decreasing")
    if vals[-1] != base + nnz:
        raise MatrixLoadError(
            f"row pointers end at {vals[-1]}, but with base {base} and "
            f"{nnz} stored entries they must end at {base + nnz}")
    return vals, base


def _assemble_csr(sa, ja, ia, n: Optional[int] = None):
    import numpy as np
    import scipy.sparse as sp

    if len(sa) != len(ja):
        raise MatrixLoadError(
            f"sa has {len(sa)} values but ja has {len(ja)} column indices; "
            "they must match")
    nnz = len(sa)
    if n is not None and len(ia) != n + 1:
        raise MatrixLoadError(
            f"ia has {len(ia)} entries; for n={n} rows it must have {n + 1}")
    vals, base = _validate_pointers(ia, nnz)
    rows = len(vals) - 1

    cols = [int(round(c)) for c in ja]
    if any(abs(c - round(c)) > 1e-9 for c in ja):
        raise MatrixLoadError("column indices must be integers")
    lo, hi = (min(cols), max(cols)) if cols else (base, base)
    if lo < base or hi >= base + rows:
        raise MatrixLoadError(
            f"column indices run {lo}..{hi}, outside [{base}, {base + rows}) "
            f"for a {rows}x{rows} matrix. Check the index base: FEAST's "
            "Fortran arrays are 1-based, SciPy's are 0-based.")

    indptr = np.array([v - base for v in vals], dtype=np.int64)
    indices = np.array([c - base for c in cols], dtype=np.int64)
    data = np.array(sa, dtype=np.float64)
    M = sp.csr_matrix((data, indices, indptr), shape=(rows, rows))
    M.sort_indices()
    return M


def describe(M) -> str:
    if sp.issparse(M):
        nnz = M.nnz
        dens = 100.0 * nnz / (M.shape[0] * M.shape[1]) if M.shape[0] else 0.0
        return f"sparse {M.shape[0]}x{M.shape[1]}, {nnz:,} nonzeros ({dens:.3f}% dense)"
    return f"dense {M.shape[0]}x{M.shape[1]}, {M.dtype}"


def check_symmetry(M, tol: float = 1e-10) -> tuple[bool, bool]:
    """Return (is_symmetric, is_hermitian). FEAST's sy/he routines require one.

    The tolerance is *relative* to the largest entry, and that matters more
    than it sounds. FEAST's own system3 has entries of order 1e-18 and an
    asymmetry of 2.6e-19 -- genuinely non-symmetric, by 9% -- yet any absolute
    tolerance above 1e-18 calls it symmetric. It was then solved by the
    Hermitian interval routines, which returned 13 eigenvalues where the true
    count is 16, with info=0 and residuals of 1e-13: the residual is computed
    against the symmetrised problem, so nothing anywhere looked wrong.

    Scaling by the matrix norm makes the test mean "symmetric to working
    precision" for a matrix of any magnitude, which is the question actually
    being asked.
    """
    if sp.issparse(M):
        scale = abs(M).max() if M.nnz else 0.0
        atol = tol * scale if scale > 0 else tol
        d = abs(M - M.T)
        sym = (d.max() if d.nnz else 0.0) <= atol
        dh = abs(M - M.getH())
        herm = (dh.max() if dh.nnz else 0.0) <= atol
        return bool(sym), bool(herm)
    M = np.asarray(M)
    scale = float(np.abs(M).max()) if M.size else 0.0
    atol = tol * scale if scale > 0 else tol
    sym = bool(np.allclose(M, M.T, rtol=0.0, atol=atol))
    herm = bool(np.allclose(M, M.conj().T, rtol=0.0, atol=atol))
    return sym, herm


# --- built-in demo problems ---------------------------------------------------
# These give the app something to solve on first launch, and every one has a
# known spectrum so the user can sanity-check the answer.

def laplacian_1d(n: int = 200, sparse: bool = True):
    """tridiag(-1,2,-1); eigenvalues 2-2cos(k*pi/(n+1))."""
    if sparse:
        return sp.diags([np.full(n - 1, -1.0), np.full(n, 2.0), np.full(n - 1, -1.0)],
                        [-1, 0, 1], format="csr")
    return (np.diag(np.full(n, 2.0)) + np.diag(np.full(n - 1, -1.0), 1)
            + np.diag(np.full(n - 1, -1.0), -1))


def laplacian_2d(k: int = 30):
    """2-D Laplacian on a k x k grid; eigenvalues 4-2cos(i*pi/(k+1))-2cos(j*pi/(k+1))."""
    t = sp.diags([np.full(k - 1, -1.0), np.full(k, 2.0), np.full(k - 1, -1.0)],
                 [-1, 0, 1], format="csr")
    eye = sp.identity(k, format="csr")
    return sp.kron(t, eye) + sp.kron(eye, t)


def random_symmetric(n: int = 300, seed: int = 0):
    rng = np.random.default_rng(seed)
    A = rng.standard_normal((n, n))
    return (A + A.T) / 2


def random_sparse_symmetric(n: int = 2000, density: float = 0.001,
                            seed: Optional[int] = None):
    """A random sparse symmetric matrix with a banded structure.

    Deliberately banded rather than a random sparsity pattern. A uniformly
    random pattern makes the shifted systems FEAST solves internally badly
    conditioned, and IFEAST's iterative inner solver then fails to converge at
    default settings -- so "generate a matrix, press Solve" would return
    info=2 and look like a broken app. Real sparse eigenproblems (finite
    difference, finite element) are structured, and banded matrices behave the
    way users expect.

    `density` sets the bandwidth: the fraction of the row that is populated.
    """
    rng = np.random.default_rng(seed)
    bandwidth = max(1, min(n - 1, int(round(density * n * n / (2 * n))) or 1))

    diags, offsets = [], []
    for k in range(1, bandwidth + 1):
        # Decay with distance from the diagonal, as a discretised operator does.
        diags.append(rng.standard_normal(n - k) / (k + 1))
        offsets.append(k)
    lower = [d.copy() for d in diags]
    all_diags = list(reversed(lower)) + [np.zeros(n)] + diags
    all_offsets = [-k for k in reversed(offsets)] + [0] + offsets

    A = sp.diags(all_diags, all_offsets, format="csr")
    # Diagonal dominance keeps it well conditioned and spreads the spectrum.
    row_abs = np.asarray(abs(A).sum(axis=1)).ravel()
    return (A + sp.diags(row_abs + rng.uniform(0.5, 1.5, n))).tocsr()


def random_spd(n: int = 300, sparse: bool = True, seed: Optional[int] = None):
    """A positive definite matrix, for use as B in a generalized problem."""
    rng = np.random.default_rng(seed)
    if sparse:
        off = rng.uniform(0.05, 0.25, n - 1)
        return sp.diags([off, np.full(n, 2.0), off], [-1, 0, 1], format="csr")
    A = rng.standard_normal((n, n))
    return A @ A.T + n * np.eye(n)


def random_hermitian(n: int = 200, seed: Optional[int] = None):
    rng = np.random.default_rng(seed)
    A = rng.standard_normal((n, n)) + 1j * rng.standard_normal((n, n))
    return (A + A.conj().T) / 2


def guess_b_path(path: str | Path) -> Optional[Path]:
    """Find the B matrix that goes with an A matrix, by FEAST's own convention.

    Upstream names generalized pairs `system1.mtx` / `system1B.mtx`, so opening
    one can offer the other instead of making the user hunt for it.
    """
    path = Path(path)
    stem = path.name
    for suffix in (".mtx", ".npy", ".npz", ".csv", ".txt"):
        if stem.endswith(suffix):
            base = stem[: -len(suffix)]
            for cand in (f"{base}B{suffix}", f"{base}_B{suffix}", f"{base}b{suffix}"):
                p = path.with_name(cand)
                if p.exists():
                    return p
    return None


def is_probably_spd(B, samples: int = 12) -> bool:
    """Cheap necessary-condition check that B is positive definite.

    FEAST's generalized interfaces require an spd B; a full Cholesky on a large
    sparse matrix is too slow for a UI hint, so this checks the diagonal (all
    entries of an spd matrix's diagonal are positive) plus a few random
    Rayleigh quotients. It can pass a non-spd matrix, but a failure is real.
    """
    diag = B.diagonal() if sp.issparse(B) else np.diag(B)
    if np.any(np.real(diag) <= 0):
        return False
    n = B.shape[0]
    rng = np.random.default_rng(0)
    for _ in range(samples):
        x = rng.standard_normal(n)
        if float(x @ (B @ x)) <= 0:
            return False
    return True


def _data_dir() -> Path:
    """Where FEAST's sample matrices live.

    A frozen app has no source tree above the package, so the bundled copy
    (added by the PyInstaller spec) is checked first.
    """
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        for cand in (base / "feast_data", base / "4.0" / "utility" / "data"):
            if cand.is_dir():
                return cand
    return Path(__file__).resolve().parent.parent.parent / "4.0" / "utility" / "data"


DATA_DIR = _data_dir()


def _feast_sample(name: str):
    """Load one of the matrix pairs FEAST ships in 4.0/utility/data."""
    A = load_matrix(DATA_DIR / f"{name}.mtx")
    bpath = DATA_DIR / f"{name}B.mtx"
    return (A, load_matrix(bpath)) if bpath.exists() else A


def demo_paths(demo_name: str):
    """Files behind a built-in demo, or (None, None) if it is generated.

    Generated code has to load the same matrices, so a demo backed by files on
    disk should say where they are instead of emitting a placeholder.
    """
    for sample in ("system1", "system3"):
        if sample in demo_name:
            a = DATA_DIR / f"{sample}.mtx"
            b = DATA_DIR / f"{sample}B.mtx"
            return (str(a) if a.exists() else None,
                    str(b) if b.exists() else None)
    return (None, None)


# Each entry is (builder, emin, emax). The builder returns either A, or an
# (A, B) pair for a generalized problem.
DEMOS = {
    "1-D Laplacian (n=200, sparse)": (lambda: laplacian_1d(200), 0.0, 0.02),
    "2-D Laplacian (30x30 grid, sparse)": (lambda: laplacian_2d(30), 0.0, 0.5),
    "1-D Laplacian (n=300, dense)": (lambda: laplacian_1d(300, sparse=False), 0.0, 0.01),
    "Random symmetric (n=300, dense)": (lambda: random_symmetric(300), -1.0, 1.0),
    # FEAST's own sample problems used to be listed here as interval searches.
    # They are now in feastpy.problems, which carries each one's real settings
    # -- its symmetry class, its storage triangle and, crucially, its search
    # GEOMETRY. system3 is declared general/non-Hermitian by its own .in file
    # and is searched with a disc centred at 0.59+0.0001i; running it as an
    # interval on [0.18, 1.0] cannot converge, and returned info=2 with eleven
    # unconverged values that looked like an answer. The catalogue entry finds
    # 16 with a residual of 5.7e-14.
}
