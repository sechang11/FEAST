# Complete FEAST: MKL, SPIKE and PFEAST

The default build (`build/build-feast.sh`) uses OpenBLAS and covers everything
most users need. This document covers the three optional pieces that unlock the
rest of FEAST, what each one buys, and exactly what was verified.

| | Unlocks | Status |
|---|---|---|
| **MKL** | sparse polynomial interfaces, PARDISO direct solvers | **working** — 26/26 examples pass |
| **PFEAST** (MPI) | 62 distributed routines, 3 levels of parallelism | **working** — 35/36 examples pass |
| **SPIKE** | 20 banded routines, 10 examples | **blocked** — the package is not obtainable |

---

## 1. MKL

Unlocks the sparse *polynomial* interfaces (`dfeast_scsrpev` and friends), which
call MKL-PARDISO directly and cannot work without it, plus the direct sparse
solvers generally.

```bash
micromamba create -p ~/mklenv -c conda-forge "mkl=2021.4.0" "mkl-devel=2021.4.0"

export MKLROOT=~/mklenv
export BLAS_LIBS="-L$MKLROOT/lib -Wl,-rpath,$MKLROOT/lib \
  -lmkl_gf_lp64 -lmkl_gnu_thread -lmkl_core -lgomp -lpthread -lm -ldl"
bash build/build-feast.sh --arch linux-x64-mkl --mkl
bash tools/run_examples.sh linux-x64-mkl          # 26/26
```

**The MKL version matters.** FEAST 4.0 calls MKL's deprecated NIST-style sparse
BLAS (`mkl_?csrmm`), which Intel has since removed. Against current MKL
(2026.x) the link fails with `undefined reference to mkl_ccsrmm_`. **2021.4.0
still has them.** Use `libmkl_gf_lp64` — the GNU Fortran interface — not
`libmkl_intel_lp64`, when building with gfortran.

Result: the two examples that fail under OpenBLAS (`Csparse_dfeast_scsrpev` and
its Fortran twin) **pass**, confirming that those failures were the missing
PARDISO and not a defect.

Before shipping MKL, read its redistribution terms — they are more restrictive
than FEAST's BSD, and it is x86-64 only, so Apple Silicon cannot use it.

## 2. PFEAST (distributed, MPI)

FEAST parallelises on three levels: **L1** search intervals, **L2** contour
points, **L3** the linear system. `build/build-pfeast.sh` builds `libpfeast.a`;
upstream's own Makefile hardcodes Debian-style wrapper names (`mpif90.openmpi`)
that do not exist on most installs, which is why it is replaced.

```bash
micromamba create -p ~/impienv -c conda-forge impi-devel "mkl=2021.4.0" "mkl-devel=2021.4.0" gfortran
export I_MPI_ROOT=~/impienv MKLROOT=~/impienv I_MPI_FABRICS=shm
export BLAS_LIBS="-L$MKLROOT/lib -Wl,-rpath,$MKLROOT/lib -lmkl_scalapack_lp64 \
  -lmkl_gf_lp64 -lmkl_gnu_thread -lmkl_core -lmkl_blacs_intelmpi_lp64 \
  -lgomp -lpthread -lm -ldl"

bash build/build-pfeast.sh --arch linux-x64-impi --mkl
MPIRUN=mpiexec MPIRUN_ARGS="" MPIRUN_NPFLAG=-n \
  bash tools/run_pfeast_examples.sh linux-x64-impi 2
```

**Use Intel MPI, not Open MPI.** L3 (the distributed linear solve) uses MKL's
*cluster* PARDISO, which needs BLACS. With conda-forge Open MPI it segfaults
inside MKL every time L3 > 1, while L3 = 1 always works — the BLACS shipped with
MKL 2021.4 is built for the Open MPI 4.x ABI, and conda-forge now ships Open MPI
5. Matching versions (Open MPI 4.1) got further but still crashed; Intel MPI,
which is what Intel supports for cluster PARDISO, works.

Also note the linker needs `-lmkl_scalapack_lp64` and `-lmkl_blacs_intelmpi_lp64`
on top of the usual MKL line, or the cluster solver has no transport.

**Result: 35 of 36 examples pass**, across all three levels, on 2, 4 and 8
ranks. Verified correct, not merely exit-zero: the L2L3 `system1` runs report
the same 16 eigenvalues the serial reference produces.

The exception is `PCsparse_pdfeast_scsrgv_lowest.c`, which had not finished
after 10 minutes on 2 ranks. Its Fortran twin passes in well under that. It was
**not** observed to fail — it exceeded the time budget, and whether it converges
eventually is untested. Raise `RUN_TIMEOUT` to find out.

### Running the examples yourself

They take arguments, and the failure mode for getting this wrong is a crash
rather than a message:

- `PFEAST-L2` — no argument.
- `PFEAST-L2L3` — `argv[1]` is how many ranks go to L3. **Omitting it divides
  by zero and dies on SIGFPE.**
- `PFEAST-L1L2L3` — wants 8 ranks and an L3 count.

## 3. SPIKE — not obtainable

The banded interfaces (20 routines, 10 examples) call SPIKE:
`spikeinit_`, `?spike_gbtrf_`, `?spike_gbtrs_`, `?gbmm_`, `?sbmm_`, `?hbmm_`.

**spike-solver.org's downloads are dead.** Every link on its download page
returns HTTP 404:

```
gfortran/libspike_openmpi.a  -> 404
gfortran/libspike_mpich2.a   -> 404
gfortran/libspike_impi.a     -> 404
```

Those links point only at prebuilt static libraries in any case; no source is
published, and the site offers no other package. The v1.0 OpenMP release
(Nov 2018) is described in [arXiv:1811.03559] but the code is not distributed
alongside it.

So this is blocked on an artefact that is not available, not on work. Options:

1. **Ask Eric.** It is his lab's package; he can almost certainly supply it, and
   that is by far the cheapest route.
2. **Write a LAPACK-backed shim.** FEAST needs six symbols, and LAPACK's banded
   routines (`?gbtrf`/`?gbtrs`) plus banded matrix-multiply could implement
   them. This is feasible but it is *not* SPIKE — no parallel banded algorithm,
   so no speedup — and the calling conventions would have to be reverse
   engineered from FEAST's call sites, which risks silently wrong results. Not
   attempted, deliberately: an eigensolver that returns confident wrong answers
   is worse than one that declines to run.

The build already supports SPIKE the moment a library exists:

```bash
SPIKE_LIBS=-lspike bash build/build-feast.sh
```

Without it, `build-feast.sh` excludes the banded objects from the shared library
(a shared library must resolve every symbol) and leaves them in the static
archive, where they are harmless until referenced.

---

## Summary of what is now reachable

| Family | Routines | Status |
|---|---|---|
| Dense Hermitian / general / polynomial | 12 + 10 | working (OpenBLAS or MKL) |
| Sparse Hermitian / general | ~34 | working (OpenBLAS or MKL) |
| Sparse polynomial | ~6 | working **with MKL** |
| PFEAST distributed | 62 | working **with MPI + MKL** |
| Banded | 20 | blocked on SPIKE |
| RCI, contours, tools | 28 | callable via `feastpy.raw` |

Of FEAST's 202 declared entry points, **182 are now buildable and exercised**;
the remaining 20 are the banded family.
