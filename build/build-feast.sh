#!/usr/bin/env bash
# Build libfeast (static + shared) from the upstream FEAST 4.0 Fortran sources.
# Works on Linux, macOS, and Windows (MSYS2/mingw64). Replaces 4.0/src/Makefile,
# which assumes $PWD is exported and that ifort is present.
#
#   ./build-feast.sh [--arch NAME] [--fc gfortran] [--mkl] [--jobs N]
#
# Output: 4.0/lib/<arch>/libfeast.a  and the matching shared library.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$HERE/../4.0/src"

FC="${FC:-gfortran}"
MKL=0
JOBS="$(getconf _NPROCESSORS_ONLN 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)"
ARCH=""

while [ $# -gt 0 ]; do
  case "$1" in
    --arch) ARCH="$2"; shift 2 ;;
    --fc)   FC="$2";   shift 2 ;;
    --mkl)  MKL=1;     shift ;;
    --jobs) JOBS="$2"; shift 2 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

# ---- platform detection -----------------------------------------------------
case "$(uname -s)" in
  Linux)          OS=linux;   SHEXT=.so    ; SHFLAG="-shared" ;;
  Darwin)         OS=macos;   SHEXT=.dylib ; SHFLAG="-dynamiclib" ;;
  MINGW*|MSYS*)   OS=windows; SHEXT=.dll   ; SHFLAG="-shared" ;;
  *) echo "unsupported platform: $(uname -s)" >&2; exit 1 ;;
esac

case "$(uname -m)" in
  arm64|aarch64) MACH=arm64 ;;
  *)             MACH=x64 ;;
esac
[ -n "$ARCH" ] || ARCH="$OS-$MACH"

# gcc on Windows resolves its scratch dir through GetTempPath(), which falls back
# to C:\WINDOWS when TMP/TEMP are unset or point at a long path. Pin it somewhere
# short and writable.
if [ "$OS" = windows ]; then
  export TMPDIR="${TMPDIR:-C:/feasttmp}"
  export TMP="$TMPDIR" TEMP="$TMPDIR"
  mkdir -p "$TMPDIR"
fi

OBJ="$HERE/obj/$ARCH"
LIB="$HERE/../4.0/lib/$ARCH"
mkdir -p "$OBJ" "$LIB"

# ---- flags ------------------------------------------------------------------
case "$FC" in
  ifort|ifx) FFLAGS="-O3 -qopenmp -cpp -fPIC" ;;
  # gfortran >= 10 rejects the same external (DGEMM, ZGEMM, ...) being called
  # with different argument types across call sites. FEAST does this deliberately,
  # so demote it to a warning rather than patching upstream sources.
  *)         FFLAGS="-O3 -fopenmp -cpp -fPIC -ffree-line-length-none -ffixed-line-length-none -fallow-argument-mismatch" ;;
esac
[ "$MKL" = 1 ] && FFLAGS="$FFLAGS -DMKL"

# FEAST 4.0 calls MKL's deprecated NIST-style sparse BLAS (mkl_?csrmm), which
# Intel removed in recent oneMKL: 2026.x links with "undefined reference to
# mkl_ccsrmm_". MKL 2021.4 still has them.
if [ "$MKL" = 1 ] && [ -z "${BLAS_LIBS:-}" ]; then
  echo "  !! --mkl needs BLAS_LIBS pointing at an MKL that still provides the" >&2
  echo "     deprecated sparse BLAS (2021.x works, 2024+ does not). e.g.:" >&2
  echo "     BLAS_LIBS=\"-L\$MKLROOT/lib -lmkl_gf_lp64 -lmkl_gnu_thread -lmkl_core -lgomp -lpthread -lm -ldl\"" >&2
fi

# ---- source list (mirrors 4.0/src/Makefile, serial FEAST only) --------------
# Kernel first: the dense/banded/sparse layers use its modules.
SOURCES="
kernel/libnum.f90
kernel/feast_tools.f90
kernel/feast_aux.f90
kernel/dzfeast.f90
dense/dzfeast_dense.f90
dense/dzfeast_pev_dense.f90
banded/dzfeast_banded.f90
sparse/sclsprim.f90
sparse/dzlsprim.f90
sparse/dzfeast_sparse.f90
sparse/dzifeast_sparse.f90
sparse/dzfeast_pev_sparse.f90
sparse/dzifeast_pev_sparse.f90
"

echo "FEAST build"
echo "  platform : $OS/$MACH  (arch tag: $ARCH)"
echo "  compiler : $FC  ($($FC --version | head -1))"
echo "  mkl      : $([ "$MKL" = 1 ] && echo yes || echo 'no (link your own BLAS/LAPACK)')"
echo "  output   : $LIB"
echo

# Fortran module files must land next to the objects, and the compile order
# above is a dependency order, so this stays serial. It is a ~1 minute build.
cd "$OBJ"
OBJECTS=""
for s in $SOURCES; do
  o="$(basename "$s" .f90).o"
  echo "  FC  $s"
  "$FC" $FFLAGS -I"$OBJ" -c "$SRC/$s" -o "$OBJ/$o"
  OBJECTS="$OBJECTS $OBJ/$o"
done

echo
echo "  AR  libfeast.a"
rm -f "$LIB/libfeast.a"
ar cr "$LIB/libfeast.a" $OBJECTS
ranlib "$LIB/libfeast.a"

# The shared library is what the Python/ctypes layer loads. It has to resolve
# BLAS/LAPACK at link time, unlike the static archive.
# The banded interface calls into SPIKE (spikeinit_, ?spike_gbtr?_, ?gbmm_),
# which upstream does NOT bundle -- it is a separate download. A static archive
# only pulls the members you reference, so banded can stay in libfeast.a
# harmlessly; a shared library must resolve everything at link time, so it is
# excluded there. Set SPIKE_LIBS=-lspike to put it back in.
SHARED_OBJECTS="$OBJECTS"
if [ -z "${SPIKE_LIBS:-}" ]; then
  SHARED_OBJECTS="$(echo "$OBJECTS" | tr ' ' '\n' | grep -v 'dzfeast_banded.o' | tr '\n' ' ')"
  echo "  ..  excluding banded interface from shared lib (no SPIKE available)"
fi

echo "  LD  libfeast$SHEXT"
BLAS_LIBS="${BLAS_LIBS:-}"
if [ -z "$BLAS_LIBS" ]; then
  if [ "$OS" = macos ]; then
    # Prefer OpenBLAS over Accelerate. Accelerate ships an old LAPACK, and
    # FEAST's non-Hermitian path returns info=-3 ("internal error in the
    # reduced eigenvalue solver") against it -- on both Apple Silicon and
    # Intel, in a configuration-dependent way. The Hermitian path is fine,
    # which is how this stayed hidden. OpenBLAS also makes the numerics the
    # same on every platform we ship.
    OB="$(brew --prefix openblas 2>/dev/null || true)"
    if [ -n "$OB" ] && [ -d "$OB/lib" ]; then
      BLAS_LIBS="-L$OB/lib -lopenblas"
    else
      echo "  !! OpenBLAS not found; falling back to Accelerate." >&2
      echo "     Non-Hermitian problems will fail with info=-3. " >&2
      echo "     Install it with: brew install openblas" >&2
      BLAS_LIBS="-framework Accelerate"
    fi
  else
    BLAS_LIBS="-lopenblas"
  fi
fi

if "$FC" $SHFLAG -o "$LIB/libfeast$SHEXT" $SHARED_OBJECTS ${SPIKE_LIBS:-} $BLAS_LIBS -fopenmp 2>"$OBJ/link.log"; then
  echo "      linked against: $BLAS_LIBS"
else
  echo "  !! shared library link failed (static archive is still good)" >&2
  sed 's/^/     /' "$OBJ/link.log" >&2
  exit 1
fi

echo
echo "Done:"
ls -la "$LIB"
