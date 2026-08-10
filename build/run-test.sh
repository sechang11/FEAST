#!/usr/bin/env bash
# Compile and run the analytic-eigenvalue smoke test against a built libfeast.
#   ./run-test.sh [arch]      (arch defaults to the tag build-feast.sh picks)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FC="${FC:-gfortran}"

case "$(uname -s)" in
  Linux)  OS=linux;  BLAS="${BLAS_LIBS:--lopenblas}" ;;
  Darwin)
    OS=macos
    # Match build-feast.sh: OpenBLAS where available, for the LAPACK reasons
    # documented there.
    if [ -z "${BLAS_LIBS:-}" ]; then
      OB="$(brew --prefix openblas 2>/dev/null || true)"
      if [ -n "$OB" ] && [ -d "$OB/lib" ]; then
        BLAS_LIBS="-L$OB/lib -lopenblas"
      else
        BLAS_LIBS="-framework Accelerate"
      fi
    fi
    BLAS="$BLAS_LIBS" ;;
  MINGW*|MSYS*)
    OS=windows; BLAS="${BLAS_LIBS:--lopenblas}"
    export TMPDIR="${TMPDIR:-C:/feasttmp}"; export TMP="$TMPDIR" TEMP="$TMPDIR"
    mkdir -p "$TMPDIR" ;;
  *) echo "unsupported platform: $(uname -s)" >&2; exit 1 ;;
esac
case "$(uname -m)" in arm64|aarch64) MACH=arm64 ;; *) MACH=x64 ;; esac

ARCH="${1:-$OS-$MACH}"
LIB="$HERE/../4.0/lib/$ARCH"

if [ ! -f "$LIB/libfeast.a" ]; then
  echo "no libfeast.a in $LIB -- run build-feast.sh first" >&2
  exit 1
fi

echo "testing $LIB/libfeast.a"

# Compile the C driver with the C compiler, but *link* with the Fortran driver.
# gfortran knows where its own runtime (libgfortran, libgomp) lives; Apple clang
# does not, and it rejects -fopenmp outright unless libomp is installed.
#
# The archive is named by full path rather than with -lfeast: a bare -lfeast
# makes the linker prefer libfeast.so sitting in the same directory, and the
# resulting binary then fails at runtime with "cannot open shared object file"
# because that directory is not on the loader path. Naming the .a keeps this a
# static, self-contained test of the archive.
cc -O2 -c "$HERE/test_feast.c" -o "$HERE/test_feast.o" -I"$HERE/../4.0/include"
"$FC" -o "$HERE/test_feast" "$HERE/test_feast.o" "$LIB/libfeast.a" $BLAS -fopenmp -lm

"$HERE/test_feast"
