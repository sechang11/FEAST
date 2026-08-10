"""Loading matrices from the formats users actually have on disk."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import scipy.io
import scipy.sparse as sp


class MatrixLoadError(ValueError):
    pass


SUPPORTED = "Matrix Market (*.mtx *.mtx.gz);;CSV (*.csv *.txt);;NumPy (*.npy *.npz);;All files (*)"


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
        delim = "," if "," in text.splitlines()[0] else None
        return np.loadtxt(str(path), delimiter=delim)
    except MatrixLoadError:
        raise
    except Exception as exc:
        raise MatrixLoadError(f"could not read {path.name}: {exc}") from exc


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


def describe(M) -> str:
    if sp.issparse(M):
        nnz = M.nnz
        dens = 100.0 * nnz / (M.shape[0] * M.shape[1]) if M.shape[0] else 0.0
        return f"sparse {M.shape[0]}x{M.shape[1]}, {nnz:,} nonzeros ({dens:.3f}% dense)"
    return f"dense {M.shape[0]}x{M.shape[1]}, {M.dtype}"


def check_symmetry(M, tol: float = 1e-10) -> tuple[bool, bool]:
    """Return (is_symmetric, is_hermitian). FEAST's sy/he routines require one."""
    if sp.issparse(M):
        d = abs(M - M.T)
        sym = (d.max() if d.nnz else 0.0) <= tol
        dh = abs(M - M.getH())
        herm = (dh.max() if dh.nnz else 0.0) <= tol
        return bool(sym), bool(herm)
    sym = bool(np.allclose(M, M.T, atol=tol))
    herm = bool(np.allclose(M, M.conj().T, atol=tol))
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


DATA_DIR = Path(__file__).resolve().parent.parent.parent / "4.0" / "utility" / "data"


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
    # FEAST's own sample: generalized, and the problem RUNNING-THE-ORIGINAL.md
    # walks through with the upstream driver.
    "FEAST sample: system1 (generalized)": (lambda: _feast_sample("system1"), 0.18, 1.0),
    "FEAST sample: system3 (generalized)": (lambda: _feast_sample("system3"), 0.18, 1.0),
}
