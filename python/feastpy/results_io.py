"""Writing solver results to disk.

Eigenvectors are usually the deliverable, not the eigenvalues, so every format
here except `values-csv` carries them.

Kept out of the GUI so a CLI or the web backend can produce identical files.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

# (key, human label, file extension) -- the GUI builds its file dialog from this.
FORMATS = [
    ("npz", "NumPy archive, everything (*.npz)", ".npz"),
    ("values-csv", "CSV, eigenvalues only (*.csv)", ".csv"),
    ("vectors-csv", "CSV, eigenvalues + eigenvectors (*.csv)", ".csv"),
    ("mtx", "Matrix Market, eigenvectors (*.mtx)", ".mtx"),
]

FORMAT_LABELS = ";;".join(label for _, label, _ in FORMATS)


def _num(x) -> str:
    """Full-precision decimal text for one number.

    repr() of a *numpy* scalar is "np.float64(0.5)" under NumPy 2, which no CSV
    reader accepts. Converting to a Python float first gives a plain round-trip
    representation.
    """
    return repr(float(x))


def format_for_label(label: str) -> str:
    for key, lab, _ in FORMATS:
        if lab == label:
            return key
    return "npz"


def extension_for(fmt: str) -> str:
    for key, _, ext in FORMATS:
        if key == fmt:
            return ext
    return ".npz"


def estimate_cells(result, fmt: str) -> int:
    """How many numbers a format will write -- used to warn before a huge CSV."""
    if fmt in ("npz", "values-csv"):
        return int(result.n_found)
    n = result.eigenvectors.shape[0] if result.eigenvectors.size else 0
    return int(n * result.n_found)


def save_results(path, result, fmt: str = "npz", *, emin=None, emax=None) -> Path:
    """Write `result` to `path` in `fmt`. Returns the path actually written."""
    path = Path(path)
    if fmt not in {k for k, _, _ in FORMATS}:
        raise ValueError(f"unknown format {fmt!r}")
    if result.n_found == 0:
        raise ValueError("nothing to export: no eigenvalues were found")

    if fmt == "npz":
        # Compressed because eigenvector blocks get large fast, and this is the
        # only format that round-trips complex vectors exactly.
        np.savez_compressed(
            path,
            eigenvalues=result.eigenvalues,
            eigenvectors=result.eigenvectors,
            residuals=result.residuals,
            info=np.array(result.info),
            loops=np.array(result.loops),
            epsout=np.array(result.epsout),
            emin=np.array(np.nan if emin is None else emin),
            emax=np.array(np.nan if emax is None else emax),
        )
        # numpy appends .npz if it is missing; report the real name.
        return path if path.suffix == ".npz" else path.with_suffix(".npz")

    if fmt == "values-csv":
        with path.open("w", encoding="utf-8", newline="") as fh:
            fh.write("index,eigenvalue,residual\n")
            for i in range(result.n_found):
                fh.write(f"{i + 1},{_num(result.eigenvalues[i])},"
                         f"{_num(result.residuals[i])}\n")
        return path

    if fmt == "vectors-csv":
        V = result.eigenvectors
        n = V.shape[0]
        complex_v = np.iscomplexobj(V)
        with path.open("w", encoding="utf-8", newline="") as fh:
            # Two header rows so a reader can tell which column belongs to which
            # eigenvalue without consulting a second file.
            fh.write("# FEAST eigenvectors: one column per eigenvalue\n")
            fh.write("eigenvalue," + ",".join(
                (f"{_num(v)},{_num(v)}" if complex_v else _num(v))
                for v in result.eigenvalues) + "\n")
            if complex_v:
                fh.write("component," + ",".join(
                    f"re_{j + 1},im_{j + 1}" for j in range(result.n_found)) + "\n")
            else:
                fh.write("component," + ",".join(
                    f"v_{j + 1}" for j in range(result.n_found)) + "\n")
            for i in range(n):
                row = [str(i + 1)]
                for j in range(result.n_found):
                    z = V[i, j]
                    row.append(f"{_num(z.real)},{_num(z.imag)}" if complex_v
                               else _num(z))
                fh.write(",".join(row) + "\n")
        return path

    # Matrix Market: the eigenvector block as a dense array.
    import scipy.io
    scipy.io.mmwrite(str(path), np.asarray(result.eigenvectors),
                     comment=(" FEAST eigenvectors, one column per eigenvalue\n"
                              " eigenvalues: "
                              + " ".join(_num(v) for v in result.eigenvalues) + "\n"))
    return path if path.suffix == ".mtx" else path.with_suffix(".mtx")
