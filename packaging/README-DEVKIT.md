# FEAST Developer Kit

Everything the FEAST 4.0 Linux release provides, prebuilt for this platform:
the libraries, the headers, upstream's examples, and the scripts that build and
test all of it. The desktop application is for people who want answers; this
kit is for people who link FEAST into their own code.

## What is in it

| | |
|---|---|
| `lib/` | `libfeast` (serial, static + shared, **banded/SPIKE included**), `libspike.a`, `libpfeast.a` (MPI) where this platform builds it |
| `include/` | FEAST's 8 C headers — note `feast_tools.h` carries four wrong prototypes upstream; see `doc/` |
| `example/` | Upstream's examples, unmodified: 36 serial (`FEAST/`), 44 distributed (`PFEAST-*/`) |
| `tools/` | `run_examples.sh`, `run_pfeast_examples.sh` — build and run every example against these libraries |
| `build/` | The build scripts, including the compatibility shims described below |
| `doc/` | Building guides and the measured per-platform compatibility matrix |

## Quick start (serial)

```bash
gfortran -O2 my_program.f90 lib/libfeast.a -lopenblas -fopenmp -o my_program
bash tools/run_examples.sh <arch>        # upstream's 36 examples: expect 34 pass
```

The two that do not pass are the polynomial `scsrpev` pair, which need MKL's
direct solver to converge at their shipped settings — on every platform,
Linux included. The polynomial *capability* works (the iterative routines
solve the same problem; the desktop app demonstrates it).

## PFEAST (MPI)

```bash
mpif90 -O2 my_mpi_program.f90 lib/libpfeast.a lib/libfeast.a lib/libspike.a \
       -lopenblas -fopenmp -o my_mpi_program
mpirun -n 4 ./my_mpi_program
bash tools/run_pfeast_examples.sh <arch> 2     # expect 40 of 44
```

**Windows note.** `libpfeast.a` here contains a small interception shim
(`build/msmpi_inplace_compat.c`) without which `MPI_ALLREDUCE(MPI_IN_PLACE,…)`
— which PFEAST calls at 222 sites — silently corrupts data under mingw
gfortran + MS-MPI. MS-MPI recognises the Fortran `MPI_IN_PLACE` sentinel by the
address of a DLL-imported COMMON variable; only Intel Fortran honours the
`!DEC$ DLLIMPORT` directive, so gfortran programs pass an address the runtime
does not recognise. The shim translates it. Link `-lmsmpi` and launch with
MS-MPI's `mpiexec -n`.

## Two shims you get for free

- `spike_blas_compat.f90` — exact `DZGEMM`/`SCGEMM` replacements. These are
  MKL-only extensions SPIKE calls; without them banded fails to link against
  any other BLAS. Verified against reference `ZGEMM` to ~1e-15.
- `msmpi_inplace_compat.c` — the MPI_IN_PLACE translation above.

## The BLAS matters

Link **OpenBLAS**. Two combinations are known-broken and both fail with
errors that look like FEAST bugs:

- **Apple Accelerate**: FEAST's non-Hermitian routines return `info=-3`
  (its LAPACK is too old).
- **Homebrew's arm64 OpenBLAS**: 8 of the 10 banded examples fail
  (`info=-3` / `info=2`) — its pthreads build clashes with FEAST's OpenMP.
  The conda-forge `openblas` (openmp variant) passes everything and is what
  these libraries were built and tested against on macOS.

## MKL (optional)

MKL unlocks the direct PARDISO solver (faster on large sparse problems, and
the missing piece for the two polynomial examples). Use **MKL 2021.4** —
newer releases removed functions FEAST calls. Recipes in
`doc/BUILDING-COMPLETE.md`. Availability: Linux, Windows and macOS Intel
natively -- all three proven at 36/36 -- and Apple Silicon via Rosetta 2,
where the macOS Intel MKL kit's own test binary has been run translated on an
M1 and passes at 5.2e-16 (MKL 2022+ refuses to run translated; 2021.4
predates the block). There is no ARM MKL and there will not be one.

## Licence

FEAST is copyright The Regents of the University of Massachusetts, Amherst
(E. Polizzi research lab), BSD-3. The sources in this kit's `example/` and the
headers are upstream's, unmodified except as documented in `doc/`.
