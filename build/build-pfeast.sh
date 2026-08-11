#!/usr/bin/env bash
# Build libpfeast -- the distributed-memory (MPI) FEAST library.
#
#   bash build/build-pfeast.sh [--arch NAME] [--mkl]
#
# PFEAST is the same solver compiled with -DMPI, plus the pdz* sources that add
# the distributed sparse interfaces. It needs an MPI Fortran wrapper (mpif90)
# on PATH; upstream's Makefile hardcodes Debian-style names like
# mpif90.openmpi, which do not exist on most installs.
#
# Output: 4.0/lib/<arch>/libpfeast.a
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$HERE/../4.0/src"

MPIFC="${MPIFC:-mpif90}"
MKL=0
ARCH=""
# MS-MPI ships no mpif90 wrapper for mingw: you compile with gfortran and point
# it at the SDK yourself. These let that work without a wrapper.
MPI_INC=""
MPI_LIB=""

while [ $# -gt 0 ]; do
  case "$1" in
    --arch) ARCH="$2"; shift 2 ;;
    --mpifc) MPIFC="$2"; shift 2 ;;
    --mpi-inc) MPI_INC="$2"; shift 2 ;;
    --mpi-lib) MPI_LIB="$2"; shift 2 ;;
    --mkl)  MKL=1; shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

command -v "$MPIFC" >/dev/null 2>&1 || {
  echo "no MPI Fortran compiler ($MPIFC) on PATH." >&2
  echo "Install one, e.g.: micromamba install -c conda-forge openmpi" >&2
  echo "or use a plain compiler with --mpifc gfortran --mpi-inc DIR --mpi-lib -lmsmpi" >&2
  exit 1
}

case "$(uname -s)" in
  Linux)        OS=linux ;;
  Darwin)       OS=macos ;;
  MINGW*|MSYS*) OS=windows
                export TMPDIR="${TMPDIR:-C:/feasttmp}"; export TMP="$TMPDIR" TEMP="$TMPDIR"
                mkdir -p "$TMPDIR" ;;
  *) echo "unsupported platform: $(uname -s)" >&2; exit 1 ;;
esac
case "$(uname -m)" in arm64|aarch64) MACH=arm64 ;; *) MACH=x64 ;; esac
[ -n "$ARCH" ] || ARCH="$OS-$MACH"

OBJ="$HERE/obj/$ARCH-pfeast"
LIB="$HERE/../4.0/lib/$ARCH"
mkdir -p "$OBJ" "$LIB"

FFLAGS="-O3 -fopenmp -cpp -fPIC -ffree-line-length-none -ffixed-line-length-none"
FFLAGS="$FFLAGS -fallow-argument-mismatch -DMPI"
[ "$MKL" = 1 ] && FFLAGS="$FFLAGS -DMKL"

# Same order as the serial build, plus the distributed sparse sources. Banded is
# omitted: it needs SPIKE, which upstream does not bundle.
SOURCES="
kernel/libnum.f90
kernel/feast_tools.f90
kernel/feast_aux.f90
kernel/dzfeast.f90
dense/dzfeast_dense.f90
dense/dzfeast_pev_dense.f90
sparse/sclsprim.f90
sparse/dzlsprim.f90
sparse/dzfeast_sparse.f90
sparse/dzifeast_sparse.f90
sparse/dzfeast_pev_sparse.f90
sparse/dzifeast_pev_sparse.f90
sparse/pdzfeast_sparse.f90
sparse/pdzifeast_sparse.f90
sparse/pdzfeast_pev_sparse.f90
sparse/pdzifeast_pev_sparse.f90
"

echo "PFEAST build"
echo "  platform : $OS/$MACH  (arch tag: $ARCH)"
echo "  mpi      : $MPIFC ${MPI_INC:+(-I$MPI_INC)} ${MPI_LIB:+$MPI_LIB}"
echo "  mkl      : $([ "$MKL" = 1 ] && echo yes || echo no)"
echo

cd "$OBJ"
OBJECTS=""
for s in $SOURCES; do
  o="$(basename "$s" .f90).o"
  echo "  MPIFC  $s"
  "$MPIFC" $FFLAGS ${MPI_INC:+-I$MPI_INC} -I"$OBJ" -c "$SRC/$s" -o "$OBJ/$o"
  OBJECTS="$OBJECTS $OBJ/$o"
done

echo
echo "  AR  libpfeast.a"
rm -f "$LIB/libpfeast.a"
ar cr "$LIB/libpfeast.a" $OBJECTS
ranlib "$LIB/libpfeast.a"

echo
echo "Done: $LIB/libpfeast.a"
ls -la "$LIB/libpfeast.a"
