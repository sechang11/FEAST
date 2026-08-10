# FEAST API coverage

What this distribution can reach of FEAST 4.0. Regenerate with:

```bash
python tools/coverage_report.py --markdown
```

## Summary

| | Count |
|---|---:|
| Entry points declared in FEAST's headers | 202 |
| Present in the library we build | **120** |
| Callable from `feastpy` | **120** (all of them, via `feastpy.raw`) |
| Wrapped ergonomically | 12 |

The 82 declared-but-absent routines are not an oversight — they need components
FEAST does not bundle. See "Not reachable" below.

| Family | Declared | In our library | Ergonomic wrapper |
|---|---:|---:|---|
| PFEAST (MPI) | 62 | 0 | — |
| Sparse CSR | 40 | 40 | `eigsh_interval`, `eig_disc` |
| Polynomial | 30 | 30 | `raw` only |
| Banded | 20 | 0 | — |
| Tools / contours | 14 | 14 | `raw.new_fpm`, `feastinit` |
| RCI | 14 | 14 | `raw` only |
| Dense Hermitian | 12 | 12 | `eigh_interval` |
| Non-Hermitian | 10 | 10 | `eig_disc` |

## Two layers

**Ergonomic** — `eigh_interval` (Hermitian, real interval), `eigsh_interval`
(sparse Hermitian), `eig_disc` (non-Hermitian and complex-symmetric, complex
disc). These pick the routine, size the workspace, marshal the arrays and
return a `FeastResult`.

**Raw** — `feastpy.raw` parses FEAST's own C headers and can call *any* routine
in the library with correct types:

```python
from feastpy import raw
raw.signature("dfeast_gcsrpev")     # argument names and types
raw.available()                     # the 120 present in this build
fpm = raw.new_fpm(fpm_2=16, fpm_3=12)
raw.call("dfeast_syev", UPLO="F", N=n, A=a, LDA=n, fpm=fpm, ...)
```

Nothing is hand-transcribed, so the signatures cannot drift from the headers.
A raw call is checked in the test suite to produce bit-identical results to the
ergonomic wrapper for the same problem.

## Not reachable, and why

**Banded (20 routines).** `dzfeast_banded.f90` calls into SPIKE
(`spikeinit_`, `?spike_gbtr?_`, `?gbmm_`), which upstream does not bundle —
it is a separate download from spike-solver.org. The objects are in
`libfeast.a` but excluded from the shared library, since a shared library must
resolve every symbol at link time. To enable: build SPIKE and rebuild with
`SPIKE_LIBS=-lspike`.

**PFEAST (62 routines).** Distributed-memory FEAST needs MPI and a separate
`libpfeast`, which we do not build. It targets clusters rather than a desktop
application. To enable: `make pfeast` with an MPI compiler, then link it.

## Known gaps in the ergonomic layer

These are callable through `raw` but have no convenience wrapper yet:

- **Polynomial eigenproblems** (`*pev`) — take a degree and a stack of
  coefficient matrices, so the signature differs enough to need its own wrapper.
- **Expert variants** (`*x`) — accept a custom contour as `Zne`/`Wne` arrays,
  for clustered spectra or non-elliptical regions.
- **RCI** — reverse communication: FEAST returns control each step and the
  caller performs the linear solves. Useful for matrix-free problems, and the
  only way to make a solve interruptible without killing a process.
- **Direct sparse** (`dfeast_scsr*` without the `i`) — present, but they need
  MKL PARDISO for the inner solves. In an OpenBLAS build the IFEAST variants
  are the working choice, which is why `eigsh_interval` uses them.

## macOS links OpenBLAS, not Accelerate

FEAST's non-Hermitian routines do not work against Apple's Accelerate: they
return `info=-3` ("internal error in the reduced eigenvalue solver") on both
Apple Silicon and Intel, in a configuration-dependent way. Accelerate ships an
old LAPACK. The Hermitian path is unaffected, so this stayed invisible until
the general routines were exercised on macOS for the first time.

`build/build-feast.sh` therefore prefers Homebrew's OpenBLAS on macOS and warns
loudly if it falls back. That also makes the numerics identical on all four
targets. If you build with Accelerate anyway, expect the Hermitian interfaces
to work and the general ones to fail.

## A note on matrix dtypes

`dfeast_ge*` returns complex eigenvalues but takes a **real** `double*` matrix.
Passing a complex array makes FEAST read interleaved real/imaginary pairs as
consecutive reals: it still "solves", but on a garbled matrix, and the symptom
is subtle — it finds eigenvalues belonging to the leading rows and silently
misses the rest. `eig_disc` sizes the matrix dtype from the routine prefix
(`d` real, `z` complex) rather than from the result type, and the test suite
pins this with a block-diagonal matrix whose eigenvalues are known exactly.
