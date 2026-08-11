#!/usr/bin/env bash
# Build SPIKE, the banded solver FEAST's banded interfaces depend on.
#
#   bash build/build-spike.sh [--src DIR] [--arch NAME]
#
# SPIKE is a separate BSD package from the same lab. It is NOT bundled with
# FEAST, and its own download page's links are dead -- the working URL is
# hidden in the site's "thanks" page:
#
#   http://www.spike-solver.org/spike-1.0.tar.gz
#
# This fetches it if it is not already present, builds it with gfortran, and
# drops libspike.a where build-feast.sh expects it. Then rebuild FEAST with
# SPIKE_LIBS set and the banded interfaces come alive.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
FC="${FC:-gfortran}"
CC="${CC:-gcc}"
SRC=""
ARCH=""
BLAS_COMPAT=1
URL="${SPIKE_URL:-http://www.spike-solver.org/spike-1.0.tar.gz}"

while [ $# -gt 0 ]; do
  case "$1" in
    --src)  SRC="$2"; shift 2 ;;
    --arch) ARCH="$2"; shift 2 ;;
    --no-blas-compat) BLAS_COMPAT=0; shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

case "$(uname -s)" in
  Linux)        OS=linux ;;
  Darwin)       OS=macos ;;
  MINGW*|MSYS*) OS=windows
                export TMPDIR="${TMPDIR:-C:/feasttmp}"
                export TMP="$TMPDIR" TEMP="$TMPDIR"; mkdir -p "$TMPDIR" ;;
  *) echo "unsupported platform: $(uname -s)" >&2; exit 1 ;;
esac
case "$(uname -m)" in arm64|aarch64) MACH=arm64 ;; *) MACH=x64 ;; esac
[ -n "$ARCH" ] || ARCH="$OS-$MACH"

WORK="$ROOT/build/spike"
mkdir -p "$WORK"

if [ -z "$SRC" ]; then
  SRC="$WORK/spike-1.0"
  if [ ! -d "$SRC" ]; then
    TAR="$WORK/spike-1.0.tar.gz"
    [ -f "$TAR" ] || { echo "fetching $URL"; curl -fsSL --max-time 300 -o "$TAR" "$URL"; }
    tar xzf "$TAR" -C "$WORK"
  fi
fi
[ -d "$SRC/src" ] || { echo "no SPIKE source at $SRC" >&2; exit 1; }

echo "SPIKE build"
echo "  source   : $SRC"
echo "  compiler : $FC"
echo "  arch tag : $ARCH"
echo

# Upstream's make.inc defaults to ifort. Rather than edit their file in place,
# hand the settings to make on the command line, which overrides it.
cd "$SRC/src"
# OPTION=1 is SPIKE's "any Fortran compiler" path. Its default, OPTION=2, swaps
# in a C wrapper to drop the Fortran runtime dependency, and its own make.inc
# marks Intel Fortran mandatory for that. Built with gfortran, OPTION=2 links
# cleanly and then segfaults at runtime.
make ARCH="$ARCH" \
     OPTION=1 \
     F90="$FC" \
     F90FLAGS="-c -O3 -cpp -fopenmp -fPIC -ffree-line-length-none -fallow-argument-mismatch" \
     CC="$CC" \
     CFLAGS="-O3 -c -fopenmp -fPIC" \
     all

LIBSRC="$SRC/lib/$ARCH/libspike.a"
[ -f "$LIBSRC" ] || LIBSRC="$(find "$SRC/lib" -name 'libspike*.a' | head -1)"
[ -f "$LIBSRC" ] || { echo "SPIKE built but no libspike.a found" >&2; exit 1; }

DEST="$ROOT/4.0/lib/$ARCH"
mkdir -p "$DEST"
cp "$LIBSRC" "$DEST/libspike.a"

# SPIKE's banded path calls DZGEMM/SCGEMM -- mixed real-by-complex products
# that are MKL extensions, not standard BLAS. Without them a build against
# OpenBLAS or Accelerate fails to link. Adding exact replacements makes banded
# work on any BLAS, which is what makes it available off Linux/x86 at all.
# Pass --no-blas-compat when linking against MKL, whose versions are faster.
if [ "$BLAS_COMPAT" = 1 ]; then
  echo "  adding DZGEMM/SCGEMM replacements (for non-MKL BLAS)"
  "$FC" -O2 -fPIC -c "$HERE/spike_blas_compat.f90" -o "$WORK/spike_blas_compat.o"
  ar r "$DEST/libspike.a" "$WORK/spike_blas_compat.o"
  ranlib "$DEST/libspike.a"
fi
echo
echo "installed: $DEST/libspike.a"

# FEAST needs these six symbol families; if any are missing the banded
# interfaces will not link and it is better to know now.
echo
echo "symbols FEAST's banded interfaces need:"
for sym in spikeinit_ cspike_gbtrf_ zspike_gbtrf_ zspike_gbtrs_ zgbmm_ dsbmm_ zhbmm_; do
  if nm -g --defined-only "$DEST/libspike.a" 2>/dev/null | grep -q " T .*$sym"; then
    echo "  found   $sym"
  else
    echo "  MISSING $sym"
  fi
done

echo
echo "Now rebuild FEAST with SPIKE:"
echo "  SPIKE_LIBS=\"-L$DEST -lspike\" bash build/build-feast.sh --arch $ARCH"
