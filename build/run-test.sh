#!/usr/bin/env bash
# Compile and run the analytic-eigenvalue smoke test against a built libfeast.
#   ./run-test.sh [arch]      (arch defaults to the same tag build-feast.sh picks)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

case "$(uname -s)" in
  Linux)        OS=linux;   BLAS="-lopenblas" ;;
  Darwin)       OS=macos;   BLAS="-framework Accelerate" ;;
  MINGW*|MSYS*) OS=windows; BLAS="-lopenblas"; export TMPDIR="${TMPDIR:-C:/feasttmp}"; export TMP="$TMPDIR" TEMP="$TMPDIR"; mkdir -p "$TMPDIR" ;;
esac
case "$(uname -m)" in arm64|aarch64) MACH=arm64 ;; *) MACH=x64 ;; esac

ARCH="${1:-$OS-$MACH}"
LIB="$HERE/../4.0/lib/$ARCH"

echo "testing $LIB/libfeast.a"
cc -O2 -o "$HERE/test_feast" "$HERE/test_feast.c" \
   -I"$HERE/../4.0/include" -L"$LIB" -lfeast $BLAS -lgfortran -fopenmp -lm

"$HERE/test_feast"
