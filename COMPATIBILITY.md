# What runs where

Every example FEAST ships, on every platform we build.

`pass` = ran and returned info=0. `info` = ran but returned a non-zero FEAST
status (almost always 2, no convergence). `skip` = not attempted.

## FEAST's 36 serial examples

Source: CI, one run, all four platforms. The macOS ARM column is discussed below.

| example | family | Windows | Linux | macOS Intel | macOS ARM |
|---|---|---|---|---|---|
| `Cbanded_dfeast_gbgv.c` | banded | pass | pass | - | pass |
| `Cbanded_dfeast_sbgv.c` | banded | pass | pass | - | pass |
| `Cbanded_zfeast_hbev.c` | banded | pass | pass | - | pass |
| `Cbanded_zfeast_sbev.c` | banded | pass | pass | - | pass |
| `Cbanded_zfeast_sbevx.c` | banded | pass | pass | - | pass |
| `Cdense_dfeast_gegv.c` | dense | pass | pass | - | pass |
| `Cdense_dfeast_sygv.c` | dense | pass | pass | - | pass |
| `Cdense_dfeast_sypev.c` | dense | pass | pass | - | pass |
| `Cdense_zfeast_heev.c` | dense | pass | pass | - | pass |
| `Cdense_zfeast_syev.c` | dense | pass | pass | - | pass |
| `Cdense_zfeast_syevx.c` | dense | pass | pass | - | pass |
| `Csparse_dfeast_gcsrgv.c` | sparse | pass | pass | - | pass |
| `Csparse_dfeast_scsrgv.c` | sparse | pass | pass | - | pass |
| `Csparse_dfeast_scsrgv_lowest.c` | sparse | pass | pass | - | pass |
| `Csparse_dfeast_scsrpev.c` | sparse | info | info | - | info |
| `Csparse_zfeast_hcsrev.c` | sparse | pass | pass | - | pass |
| `Csparse_zfeast_scsrev.c` | sparse | pass | pass | - | pass |
| `Csparse_zfeast_scsrevx.c` | sparse | pass | pass | - | pass |
| `F90banded_dfeast_gbgv.f90` | banded | pass | pass | - | pass |
| `F90banded_dfeast_sbgv.f90` | banded | pass | pass | - | pass |
| `F90banded_zfeast_hbev.f90` | banded | pass | pass | - | pass |
| `F90banded_zfeast_sbev.f90` | banded | pass | pass | - | pass |
| `F90banded_zfeast_sbevx.f90` | banded | pass | pass | - | pass |
| `F90dense_dfeast_gegv.f90` | dense | pass | pass | - | pass |
| `F90dense_dfeast_sygv.f90` | dense | pass | pass | - | pass |
| `F90dense_dfeast_sypev.f90` | dense | pass | pass | - | pass |
| `F90dense_zfeast_heev.f90` | dense | pass | pass | - | pass |
| `F90dense_zfeast_syev.f90` | dense | pass | pass | - | pass |
| `F90dense_zfeast_syevx.f90` | dense | pass | pass | - | pass |
| `F90sparse_dfeast_gcsrgv.f90` | sparse | pass | pass | - | pass |
| `F90sparse_dfeast_scsrgv.f90` | sparse | pass | pass | - | pass |
| `F90sparse_dfeast_scsrgv_lowest.f90` | sparse | pass | pass | - | pass |
| `F90sparse_dfeast_scsrpev.f90` | sparse | info | info | - | info |
| `F90sparse_zfeast_hcsrev.f90` | sparse | pass | pass | - | pass |
| `F90sparse_zfeast_scsrev.f90` | sparse | pass | pass | - | pass |
| `F90sparse_zfeast_scsrevx.f90` | sparse | pass | pass | - | pass |

| | Windows | Linux | macOS Intel | macOS ARM |
|---|---|---|---|---|
| passed / failed / skipped | 34/2/0 | 34/2/0 | not captured | 26/10/0 |

## PFEAST's 44 distributed examples

Measured on the M1 (OpenMPI 5.0.10, 2 ranks). Linux was last measured before
the runner fixes and is not comparable; Windows cannot run PFEAST at all.

| example | macOS ARM | Linux | Windows |
|---|---|---|---|
| `3PCsparse_pzfeast_hcsrev.c` | pass | not re-measured | cannot run |
| `3PF90sparse_pzfeast_hcsrev.f90` | pass | not re-measured | cannot run |
| `PCbanded_dfeast_gbgv.c` | pass | not re-measured | cannot run |
| `PCbanded_dfeast_sbgv.c` | pass | not re-measured | cannot run |
| `PCbanded_zfeast_hbev.c` | pass | not re-measured | cannot run |
| `PCbanded_zfeast_sbev.c` | pass | not re-measured | cannot run |
| `PCdense_dfeast_gegv.c` | pass | not re-measured | cannot run |
| `PCdense_dfeast_sygv.c` | pass | not re-measured | cannot run |
| `PCdense_dfeast_sypev.c` | pass | not re-measured | cannot run |
| `PCdense_zfeast_heev.c` | pass | not re-measured | cannot run |
| `PCdense_zfeast_syev.c` | pass | not re-measured | cannot run |
| `PCsparse_dfeast_gcsrgv.c` | pass | not re-measured | cannot run |
| `PCsparse_dfeast_scsrgv.c` | pass | not re-measured | cannot run |
| `PCsparse_dfeast_scsrgv_lowest.c` | pass | not re-measured | cannot run |
| `PCsparse_dfeast_scsrpev.c` | info | not re-measured | cannot run |
| `PCsparse_pdfeast_gcsrgv.c` | pass | not re-measured | cannot run |
| `PCsparse_pdfeast_scsrgv.c` | pass | not re-measured | cannot run |
| `PCsparse_pdfeast_scsrgv_lowest.c` | pass | not re-measured | cannot run |
| `PCsparse_pdfeast_scsrpev.c` | info | not re-measured | cannot run |
| `PCsparse_pzfeast_hcsrev.c` | pass | not re-measured | cannot run |
| `PCsparse_pzfeast_scsrev.c` | pass | not re-measured | cannot run |
| `PCsparse_zfeast_hcsrev.c` | pass | not re-measured | cannot run |
| `PCsparse_zfeast_scsrev.c` | pass | not re-measured | cannot run |
| `PF90banded_dfeast_gbgv.f90` | pass | not re-measured | cannot run |
| `PF90banded_dfeast_sbgv.f90` | pass | not re-measured | cannot run |
| `PF90banded_zfeast_hbev.f90` | pass | not re-measured | cannot run |
| `PF90banded_zfeast_sbev.f90` | pass | not re-measured | cannot run |
| `PF90dense_dfeast_gegv.f90` | pass | not re-measured | cannot run |
| `PF90dense_dfeast_sygv.f90` | pass | not re-measured | cannot run |
| `PF90dense_dfeast_sypev.f90` | pass | not re-measured | cannot run |
| `PF90dense_zfeast_heev.f90` | pass | not re-measured | cannot run |
| `PF90dense_zfeast_syev.f90` | pass | not re-measured | cannot run |
| `PF90sparse_dfeast_gcsrgv.f90` | pass | not re-measured | cannot run |
| `PF90sparse_dfeast_scsrgv.f90` | pass | not re-measured | cannot run |
| `PF90sparse_dfeast_scsrgv_lowest.f90` | pass | not re-measured | cannot run |
| `PF90sparse_dfeast_scsrpev.f90` | info | not re-measured | cannot run |
| `PF90sparse_pdfeast_gcsrgv.f90` | pass | not re-measured | cannot run |
| `PF90sparse_pdfeast_scsrgv.f90` | pass | not re-measured | cannot run |
| `PF90sparse_pdfeast_scsrgv_lowest.f90` | pass | not re-measured | cannot run |
| `PF90sparse_pdfeast_scsrpev.f90` | info | not re-measured | cannot run |
| `PF90sparse_pzfeast_hcsrev.f90` | pass | not re-measured | cannot run |
| `PF90sparse_pzfeast_scsrev.f90` | pass | not re-measured | cannot run |
| `PF90sparse_zfeast_hcsrev.f90` | pass | not re-measured | cannot run |
| `PF90sparse_zfeast_scsrev.f90` | pass | not re-measured | cannot run |

**macOS ARM: 40 passed, 4 failed, 0 skipped.**

## Where the platforms genuinely differ

Only two cells in the serial table are not `pass` everywhere, and they have
different causes.

### The two polynomial examples fail on every platform

`Csparse_dfeast_scsrpev` and `F90sparse_dfeast_scsrpev` return `info=2` (no
convergence) on Windows, Linux, macOS Intel and macOS ARM alike. This is not a
platform difference: the shipped libraries contain no MKL, so the inner linear
systems are solved iteratively, and this problem does not reach the default
1e-12 tolerance that way. The same problem converges to 9.4e-07 through the
desktop app, which sizes the subspace at M0=100 and asks for 1e-6 instead of
inheriting the example's settings.

### Banded on macOS ARM -- fixed

This section previously recorded 8 of the 10 banded examples failing on Apple
Silicon with `info=-3` and `info=2`, while passing on a real M1. **Fixed**: all
ten now pass on every platform, and no example differs between platforms at all.

The cause was the BLAS, and not its version.

CI installed OpenBLAS through Homebrew; the M1 test used the conda-forge
build:

    CI (fails)   -L/opt/homebrew/opt/openblas/lib -lopenblas
    M1 (passes)  -L$HOME/feastenv/lib -lopenblas        (conda-forge)

`info=-3` is "internal error in the reduced eigenvalue solver", the same code
Apple's Accelerate produces against FEAST's non-Hermitian path, which suggests
Homebrew's arm64 OpenBLAS has a LAPACK problem in the same area rather than a
threading one -- thread count made no difference.

Homebrew's arm64 bottle is threaded with pthreads; the conda-forge build is the
`openmp_` variant. FEAST is compiled `-fopenmp` and the banded path runs through
SPIKE, which is heavily OpenMP-parallel, so a pthread-threaded BLAS underneath
it is a known source of exactly this failure. Thread count made no difference on
the hardware, which ruled out simple oversubscription.

This mattered beyond CI, because CI builds the library we ship: the banded
routines in the Apple Silicon build carried the same defect. macOS now links
conda-forge OpenBLAS, and the packaging bundles it -- the first attempt fixed
the numerics and broke the bundle, which shipped a `libfeast` referencing an
`@rpath/libopenblas.0.dylib` that was not there. The self-test in a clean
environment caught that before it reached anyone.

### Windows PFEAST -- fixed

This section previously recorded that PFEAST could not run on Windows:
`MPI_ALLREDUCE(MPI_IN_PLACE, ...)`, which PFEAST calls at 222 sites, silently
corrupts data under mingw gfortran + MS-MPI. The mechanism: MS-MPI recognises
the Fortran sentinel by the address of a COMMON variable its `mpif.h` marks
`!DEC$ ATTRIBUTES DLLIMPORT` -- a directive only Intel Fortran honours, so
gfortran programs pass an address the runtime has never seen and it reduces
garbage.

**Fixed** by a 20-line interception shim (`build/msmpi_inplace_compat.c`),
compiled into `libpfeast.a` on Windows, which swaps the program-local sentinel
for the C `MPI_IN_PLACE`. Measured on real hardware with MS-MPI:

    passed 40, failed 4, skipped 0

-- identical to Apple Silicon, banded included. The four failures are the
polynomial pair that needs MKL on every platform.

## Full-feature builds: the original's 36/36, on every OS

The two polynomial examples fail on every MKL-free build because they need the
direct PARDISO solver. With MKL 2021.4 they pass -- and that build now exists
on every platform, not only Linux:

| configuration | examples | where proven |
|---|---|---|
| Linux + MKL + SPIKE | **36/36** | CI, and by hand before it |
| Windows + MKL + SPIKE | **36/36** | real hardware (mingw gfortran linked directly against `mkl_rt.1.dll`) |
| macOS Intel + MKL + SPIKE | **36/36** | CI |
| Apple Silicon | 34/36 native; the Intel MKL kit **runs translated under Rosetta 2 -- measured on an M1, PASS at 5.2e-16** | real hardware |

Three findings made this possible, each recorded in the build scripts:

1. **Windows never needed Intel Fortran.** `mkl_rt.1.dll` exports the
   gfortran-convention names (`dgemm_`, `pardiso_`, `mkl_dcsrmm_`), and
   binutils links directly against a DLL. The pip wheel `mkl==2021.4.0`
   carries the complete runtime.
2. **The one real ABI gap is `zdotc`/`cdotc`** (complex-returning BLAS,
   36 call sites). `build/mkl_gfortran_abi_compat.c` provides both with
   gfortran's convention by construction, forwarding to MKL's pointer-based
   CBLAS.
3. **MKL 2021 predates Intel's Rosetta block** (2022+ refuses to run
   translated), and 2021.4 is simultaneously the newest MKL that still has
   the sparse routines FEAST calls. The version FEAST needs is exactly the
   version Apple Silicon can still run.

The full-feature Developer Kits (`FEAST-devkit-<os>-mkl`) bundle the MKL
runtime -- redistribution is permitted by Intel's Simplified Software
License -- plus the gfortran runtime on macOS, with install names rewritten
so the kit runs on a machine with nothing installed.

## Routine coverage, by platform

Identical on all four: **140 of 140** non-MPI entry points are present in the
shipped library and callable from `feastpy`.

| family | declared | in the shipped library |
|---|---|---|
| sparse CSR | 40 | 40 |
| polynomial | 30 | 30 |
| banded | 20 | 20 |
| tools / contours | 14 | 14 |
| RCI | 14 | 14 |
| dense Hermitian | 12 | 12 |
| non-Hermitian | 10 | 10 |
| PFEAST (MPI) | 60 | 0 -- separate library, needs MPI |

## The 13 built-in problems in the desktop app

Measured on Windows; the solver path is identical on every platform.

| problem | n | search | result |
|---|---|---|---|
| Hello world (4x4) | 4 | interval | 2 eigenvalues, residual 3e-14 |
| system1 | 1,671 | interval | 16, residual 7.7e-14 |
| system2 (complex Hermitian) | 600 | interval | 30, residual 6.0e-13 |
| system3 (non-Hermitian) | 1,671 | disc | 16, residual 5.7e-14 |
| system4 (complex symmetric) | 801 | disc | 6, residual 9.7e-13 |
| system5 (quadratic polynomial) | 1,000 | disc | 20, residual 9.4e-07 |
| Carbon nanotube | 12,450 | interval | 100, residual 3.5e-13, ~2.5 min |
| Sodium cluster Na5 | 5,832 | interval | 100, residual 1.5e-13, ~40 s |
| Structural stiffness bcsstk11 | 1,473 | interval | 800, residual 2.4e-13, ~6 min |
| Carbon monoxide | 8,478 | interval | **info=2** at the shipped settings |
| Benzene C6H6 | 49,192 | interval | **info=1**, finds nothing at those settings |
| Grcar matrix | 100 | disc | **does not converge without MKL** |
| Quantum chemistry qc324 | 324 | disc | 17 found, converges only slowly |

The last four are limited by the absence of a direct solver, not by the
platform. Each says so on its own entry in the application.
