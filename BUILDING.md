# Building FEAST + the desktop app

Upstream FEAST 4.0 lives untouched in `4.0/`. Everything added sits alongside it:

```
build/     build-feast.sh, run-test.sh, test_feast.c   -- native library + numerical test
python/    feastpy/                                     -- ctypes binding (the shared core)
gui/       app.py                                       -- PySide6 desktop app
.github/   workflows/build-libfeast.yml                 -- Linux / macOS / Windows CI
```

## Why not `4.0/src/Makefile`

The upstream Makefile defaults to `ifort`, and it builds paths from `$(PWD)`,
which is only set if the invoking shell exports it. It also inherits whatever
`TMP` the environment has. `build/build-feast.sh` replaces it and works
identically on all three platforms.

## Build the native library

```bash
bash build/build-feast.sh          # auto-detects platform, writes 4.0/lib/<os>-<arch>/
bash build/run-test.sh             # analytic-eigenvalue check, prints PASS/FAIL
```

Options: `--fc ifx`, `--mkl`, `--arch NAME`. `BLAS_LIBS` and `SPIKE_LIBS`
override link-time dependencies.

### Toolchain per platform

| Platform | Compiler | BLAS/LAPACK |
|---|---|---|
| Linux | `gfortran` (apt: `gfortran`) | `libopenblas-dev` |
| macOS | `gfortran` (brew: `gcc`) | Accelerate framework (built in) |
| Windows | MSYS2 MINGW64 `mingw-w64-x86_64-gcc-fortran` | `mingw-w64-x86_64-openblas` |

## Three things that will bite you

1. **`-fallow-argument-mismatch` is required.** gfortran 10+ rejects calling the
   same external (`DGEMM`, ...) with different argument types at different call
   sites. FEAST does this deliberately. The flag demotes it to a warning; no
   upstream source is patched.

2. **The banded interface needs SPIKE, which upstream does not bundle.**
   `dzfeast_banded.f90` calls `spikeinit_`, `?spike_gbtr?_`, `?gbmm_`. Those
   live in the separate SPIKE package. A static archive only pulls referenced
   members, so banded stays in `libfeast.a` harmlessly, but it is excluded from
   the shared library. Set `SPIKE_LIBS=-lspike` to include it.

3. **`MKL=no` means no PARDISO, so use the IFEAST sparse routines.** The direct
   sparse solvers (`dfeast_scsrev_`) need MKL-PARDISO for the inner linear
   solves. In an OpenBLAS build they are unusable. The iterative variants
   (`difeast_scsrev_`) work everywhere, and are what `feastpy.eigsh_interval`
   calls. Building with `--mkl` against oneAPI would let you switch.

On Windows, gcc picks its scratch directory via `GetTempPath()`, which falls
back to `C:\WINDOWS` (unwritable) when `TMP`/`TEMP` are unset or very long. The
build script pins `TMPDIR=C:/feasttmp`.

## Python core

```bash
python -m venv .venv && .venv/bin/pip install numpy scipy PySide6 pyqtgraph
cd python && python test_feastpy.py       # 7/7 expected
```

`feastpy` finds the library via `FEAST_LIBRARY`, then a bundled `_native/` dir
(frozen apps), then `4.0/lib/<os>-<arch>/`.

```python
import feastpy
r = feastpy.eigh_interval(A, emin=0.0, emax=0.05)      # dense sym/Hermitian
r = feastpy.eigsh_interval(A_csr, emin=0.0, emax=0.05) # sparse CSR
r.eigenvalues, r.eigenvectors, r.residuals, r.message
```

FEAST takes an *interval*, not a count — that is the whole point of the method,
and the API keeps it that way. `m0` is a subspace size: an over-estimate of how
many eigenvalues are in the interval. Too small returns `info=3`.

## Desktop app

```bash
.venv/bin/python gui/app.py
python gui/verify_gui.py shot.png     # headless: solves and screenshots
```

Same file runs on all three platforms. The solve runs on a worker thread, so
the window stays responsive.

## Status

All four targets build the library, pass the analytic test, pass the `feastpy`
binding tests, and pass the headless GUI check — in CI, on every push.

| Target | Library | `run-test.sh` | `feastpy` | GUI check |
|---|---|---|---|---|
| windows-x64 | CI + local | 1.7e-16 | 35/35 | pass |
| linux-x64 | CI + local | 2.0e-16 | 35/35 | pass |
| macos-arm64 | CI | 1.9e-16 | 35/35 | pass |
| macos-x64 | CI | pass | 35/35 | pass |
| macos-universal | `lipo` of both | — | — | — |

The GUI check is not a smoke test: it drives spectral bounds, the count
estimate, the interval band, a solve, the convergence capture, the generalized
`system1` problem (asserting the same 16 eigenvalues the upstream driver
finds), all four export formats, code generation (running the generated Python
and compiling the generated C), cancellation (asserting the child process is
gone), and the diagnose-and-fix loop. Screenshots are uploaded as artifacts.

The universal dylib is checked at the Mach-O level rather than assumed from a
green job: CI asserts both `x86_64` and `arm64` slices are present.

### Platform differences worth knowing

- **An undersized `M0` does not produce the same status code everywhere.**
  OpenBLAS returns `info=3` ("subspace too small"); Apple Silicon's Accelerate
  returns `info=1` ("no eigenvalue found") for identical input. Do not assert
  on the code — assert on the behaviour. `diagnose()` leads with the `M0` fix
  when `M0` is implausibly small, so `info=1` does not misdirect the user.
- **Windows needs the mingw DLL directory declared.** CPython 3.8+ does not
  consult `PATH` for a loaded DLL's dependencies. `feastpy` reads
  `FEAST_DLL_DIR`; CI sets it because the runners put MSYS2 under `RUNNER_TEMP`
  rather than `C:\msys64`.
- **Apple's clang rejects `-fopenmp`** and does not know where `libgfortran`
  lives, so C is compiled with `cc` and linked with `gfortran`.
- **Use `macos-15-intel`, not `macos-13`.** That image was retired, and jobs
  requesting it queue forever rather than failing — which reads as a runner
  backlog instead of a bad label.

Linux was also verified on a Fedora 44 box using a conda-forge toolchain in
`$HOME` (no root needed) — `micromamba create -p ~/feastenv -c conda-forge
gfortran openblas python numpy scipy pyside6 pyqtgraph` — a useful recipe when
you cannot install system packages.

### Still to do

Nothing is signed or notarized, so macOS will refuse the app on first launch
until it is (`xattr -dr com.apple.quarantine` to test before then), and Windows
will show a SmartScreen warning. Packaging (PyInstaller/NSIS/DMG) has not
started.
