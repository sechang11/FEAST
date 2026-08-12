# FEAST — desktop application, Python bindings and web calculator

A cross-platform application built on **FEAST 4.0**, Eric Polizzi's
contour-integration eigensolver (UMass Amherst, BSD-3).

FEAST answers *"give me every eigenvalue in this range"* rather than *"give me
the ten smallest"*. Upstream ships it as a Fortran library with no interface:
you compile it yourself and call it from your own code, on Linux. This repo
adds the parts that make it something you can run — on Windows, macOS and
Linux — without taking anything away from the library underneath.

---

## What is here

| | |
|---|---|
| `gui/` | The desktop application. PySide6 + pyqtgraph. |
| `python/feastpy/` | Python bindings. All 202 FEAST routines are callable. |
| `web/` | FastAPI backend and a free browser calculator. |
| `build/` | Build scripts for libfeast, SPIKE and PFEAST. |
| `packaging/` | PyInstaller spec and release collection. |
| `tools/` | Coverage report, example runners, header checker, benchmarks. |
| `licensing/` | Offline Ed25519 licence keys. Inert until a key is configured. |
| `4.0/` | Upstream FEAST 4.0, unmodified. |

Start with **[PLAIN-ENGLISH.md](PLAIN-ENGLISH.md)** — what FEAST is, what was in
the original package, what works on which platform, and what to ask Eric. No
jargon that isn't explained.

---

## Running the application

Download the build for your platform, unpack it and run it. Nothing to install:
no Python, no compiler, no MKL.

    Windows   FEAST.exe
    Linux     ./FEAST
    macOS     FEAST.app

macOS builds are **not yet signed or notarized**, so a Mac will refuse to open
one downloaded through a browser. Right-click → Open, or:

    xattr -dr com.apple.quarantine FEAST.app

To collect every platform's build into `release/`, from a green CI run:

    bash packaging/fetch-releases.sh

### What it does

Six views, each answering a different question:

- **Matrix** — what the matrix actually is. Exact numbers below 24×24, a
  sparsity pattern above, plus bandwidth and a symmetry audit.
- **Spectrum** — where the eigenvalues are. A draggable interval on the real
  line, or the complex plane with a search disc for non-Hermitian problems.
- **Filter & contour** — the rational filter and the quadrature contour: the
  objects FEAST's papers are about, and the reason its parameters behave as
  they do. Draws before you solve, so tuning is free.
- **Accuracy** — eigenvalue against residual, with the subspace slots FEAST
  examined and rejected shown hollow.
- **Eigenvector** — click an eigenvalue, see its eigenvector.
- **Convergence** — error per refinement loop.

All 13 problems FEAST ships are built in, from its 4×4 hello-world to a
49,192-row benzene molecule, each with the settings from its own `.in` file.
Every algorithmic option is explained in plain English behind
*"What do these options do?"*.

---

## Using the bindings

```python
import feastpy

r = feastpy.eigsh_interval(A, emin=0.0, emax=0.05, m0=20)
r.eigenvalues, r.eigenvectors, r.residuals
```

- `eigh_interval` / `eigsh_interval` — Hermitian, dense or sparse, real interval
- `eig_disc` — non-Hermitian, a disc in the complex plane
- `eig_polynomial` — `(A0 + λA1 + λ²A2 …)x = 0`, solved directly
- `estimate_count`, `spectral_bounds` — size the problem before solving it
- `feastpy.raw` — any of the 202 routines, signature parsed from FEAST's headers

```python
from feastpy import problems
p = problems.get("system2")          # FEAST's own complex Hermitian sample
A, B = problems.load(p)
```

---

## Building from source

    bash build/build-spike.sh          # optional: unlocks the banded routines
    bash build/build-feast.sh --spike
    bash build/run-test.sh <arch>

Needs gfortran and a BLAS. See **[BUILDING.md](BUILDING.md)**, and
**[BUILDING-COMPLETE.md](BUILDING-COMPLETE.md)** for MKL, SPIKE and PFEAST.

Two things the upstream instructions do not mention: FEAST does not compile
with gfortran 10 or newer without `-fallow-argument-mismatch`, and on macOS it
must be linked against OpenBLAS rather than Apple's Accelerate, whose older
LAPACK makes the non-Hermitian routines fail with an internal error.

---

## Testing

    python python/test_feastpy.py           # 62 binding tests
    QT_QPA_PLATFORM=offscreen python gui/verify_gui.py out.png
    python tools/check_headers.py           # C headers vs the Fortran
    bash tools/run_examples.sh <arch>       # FEAST's own 36 example programs

CI runs all of these on Windows, Linux, macOS Intel and Apple Silicon on every
push, then packages the app and self-tests the bundle in a stripped
environment.

---

## Known limitations

- **macOS and Windows builds are unsigned.** Signing and notarization need
  certificates that have not been bought.
- **No MKL in the shipped libraries**, so every inner solve is iterative. Three
  built-in problems are affected and each says so on its own entry: `grcar`
  does not converge at all, `c6h6` finds nothing at its shipped settings, and
  `co` stops short. A direct solver would settle all three.
- **PFEAST builds on Windows but every binary crashes.** Undiagnosed. It is for
  clusters, which is not where this application runs.
- **The web calculator is interval-only** and capped at 30 seconds. That is a
  page nobody has built, not a limit of the backend.
- **Licensing is switched off.** The application runs unrestricted until a
  signing key is configured.

## Reported upstream

**[FOR-ERIC-header-bug.md](FOR-ERIC-header-bug.md)** — four routines in FEAST's
`feast_tools.h` are declared with one argument fewer than the Fortran defines,
which corrupts memory for any C caller. Verified against the source, with a
reproduction script and a patch. `tools/check_headers.py` guards against a
fifth appearing.

## Licence

FEAST is BSD-3 (Eric Polizzi). `4.0/` is unmodified upstream; see
`4.0/license.txt`. This project is being built for Eric.
