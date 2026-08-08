# Running the original FEAST on Linux

What using FEAST 4.0 looks like *today*, without our GUI. Every command below
was run on Fedora 44 with gfortran 16.1.1; the outputs are real.

Useful as a baseline for what the desktop app has to beat.

---

## 1. Install a toolchain

```bash
sudo dnf install -y gcc-gfortran openblas-devel      # Fedora
sudo apt install -y gfortran libopenblas-dev         # Debian/Ubuntu
```

## 2. Build the library

The documented command is:

```bash
cd 4.0/src
make F90=gfortran MKL=no feast
```

**This fails on any modern gfortran.** You get roughly 400 lines of:

```
Error: Type mismatch between actual argument at (1) and actual argument at (2)
       (COMPLEX(8)/REAL(8)).
make: *** [Makefile:139: kernel/dzfeast.o] Error 1
```

Nothing in the README or the user guide mentions this. gfortran 10 (released
2020) started rejecting calls to the same external procedure with different
argument types; FEAST does this deliberately when it passes real and complex
arrays to the same BLAS routine. The code is fine — the compiler default changed.

The fix is to override the flags on the command line:

```bash
cd 4.0/src
make F90=gfortran MKL=no \
  F90FLAGS="-O3 -fopenmp -ffree-line-length-none -ffixed-line-length-none -cpp -fallow-argument-mismatch" \
  feast
```

That produces `4.0/lib/x64/libfeast.a` (~1.5 MB).

> On Windows the upstream Makefile fails for a second, unrelated reason: it
> builds paths from `$(PWD)`, which is only set if the invoking shell exports
> it. `build/build-feast.sh` handles all of this — see BUILDING.md.

## 3. Build the driver

`4.0/utility/FEAST/Makefile` assumes Intel MKL. With OpenBLAS you compile by
hand, as its own help text tells you:

```bash
cd 4.0/utility/FEAST
gfortran -O3 -fopenmp -ffree-line-length-none -ffixed-line-length-none \
  -o driver_feast_sparse driver_feast_sparse.f90 \
  ../../lib/x64/libfeast.a -lopenblas
```

Without MKL there is no PARDISO, so the sparse interfaces fall back to IFEAST
(iterative). That is why the sample inputs set `fpm(43)=1`.

## 4. Describe your problem in a `.in` file

The driver takes a *base name* and reads `<name>.in` beside `<name>.mtx`.
`4.0/utility/data/system1.in`:

```
s       ! s: symmetric, h: hermitian, g: general
g       ! e=standard or g=generalized eigenvalue problem
d       ! (d,z) precision i.e (double real,double complex)
F       ! UPLO (L: lower, U: upper, F: full)
0.18d0  ! Emin
1.00d0  ! Emax
30      ! M0 search subspace (M0>=M)
2       ! How many changes from default fpm[1,64]
1 1     ! fpm(1)=1  example comments on/off
43 1    ! switch to IFEAST
```

Line order is positional and undocumented outside this file. There is no
validation: a wrong line means a wrong answer or a crash.

## 5. Run it

```bash
cd 4.0/utility/data
../FEAST/driver_feast_sparse ./system1
```

Real output, abridged:

```
 matrix -coordinate format- size        1671
 sparse matrix A- nnz       11435

Routine DIFEAST_SCSRGV
Solving AX=eBX with A real symmetric and B spd
| Emin              |  1.7999999999999999E-01 |
| Emax              |  1.0000000000000000E+00 |
| #Contour nodes    |  4   (half-contour)     |
| System solver     |  BiCGstab               |
| Size subspace     |     30                  |

#It |  #Eig  |     Trace       |  Error-Trace   |  Max-Residual
  0     16      9.5174696468E+00   1.0000000E+00   8.8472770E-02
  ...
  8     16      9.4955970541E+00   5.3290705E-15   7.0934108E-13

==>FEAST has successfully converged with Residual tolerance <1E-12
   # Eigenvalue found  16 from 2.1678880018719407E-01 to 9.8979059932430291E-01
| Total time (s)    |      0.1720      |

 FEAST OUTPUT INFO           0
 Eigenvalues saved in file: eig.out
```

Results land in `eig.out` in the current directory.

## 6. The examples

`4.0/example/FEAST` has ~36 programs covering dense/banded/sparse in C and
Fortran:

```bash
cd 4.0/example/FEAST
make COMP=gnu rallF          # compile and run all Fortran examples
```

The Makefile defaults to Intel and assumes MKL. `BANDED=yes` additionally
requires the SPIKE solver from spike-solver.org, which is **not bundled** —
`dzfeast_banded.f90` calls `spikeinit_`, `?spike_gbtr?_` and `?gbmm_`, and
without SPIKE those are undefined at link time.

---

## What this costs a user

To get one set of eigenvalues out of the original:

1. Install a Fortran compiler and BLAS.
2. Hit a build failure with no documented fix, and know to add
   `-fallow-argument-mismatch`.
3. Know that no-MKL means no PARDISO means set `fpm(43)=1`.
4. Hand-compile the driver because its Makefile assumes MKL.
5. Write a positional, unvalidated `.in` file.
6. Convert your matrix to FEAST's coordinate format.
7. Guess `M0`, and re-run if it was too small.
8. Read `eig.out`.

Steps 2, 3 and 4 each require knowledge that is not in the documentation.

## The same problem in the GUI

Open `system1.mtx`, set the interval to `[0.18, 1.0]`, press Solve. Eigenvalues
appear in a sortable table with residuals and a spectrum plot; `M0` is retried
automatically if it was too small; `info` codes are shown in English.

The two agree to **1.7e-15**:

```
upstream driver : 16 eigenvalues
feastpy         : 16 eigenvalues
max |difference|: 1.721e-15
ours     0.216788800187195 .. 0.989790599324303
upstream 0.216788800187194 .. 0.989790599324303
```

Same solver, same answer. The product is everything around it.

### A compatibility note

FEAST's own `.mtx` files are inconsistent: `bcsstk11.mtx` has the
`%%MatrixMarket` banner, `system1.mtx` and `helloworld.mtx` do not — they are
bare `nrow ncol nnz` + triplets, sometimes with Fortran `D` exponents
(`7.1D-19`). `scipy.io.mmread` rejects the bare ones outright. `feastpy`'s
loader falls back to a hand parser so the app can open the data FEAST ships.
