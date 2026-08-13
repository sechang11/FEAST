#!/usr/bin/env bash
# Assemble the FEAST Developer Kit for one platform.
#
#   bash packaging/build-devkit.sh <arch-tag>
#
# The desktop application is for people who want answers; this kit is for
# people who want the LIBRARY -- everything upstream's Linux release provides,
# prebuilt: libfeast (serial, SPIKE included), libpfeast (MPI), the headers,
# all of upstream's examples, and the runners that exercise them. It is the
# other half of "full functionality on every OS": PFEAST is linked into MPI
# programs and launched with mpirun, so its natural deliverable is a library
# and examples, not a window.
#
# Output: FEAST-devkit-<arch>.tar.gz (unix) / .zip (windows), one top-level
# directory, built on the machine that produced the binaries so file
# permissions are real.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
ARCH="${1:?usage: build-devkit.sh <arch-tag>}"

LIBDIR="$ROOT/4.0/lib/$ARCH"
[ -d "$LIBDIR" ] || { echo "no $LIBDIR -- build the libraries first" >&2; exit 1; }

STAGE="$ROOT/devkit-stage/FEAST-devkit-$ARCH"
rm -rf "$ROOT/devkit-stage"
mkdir -p "$STAGE/lib" "$STAGE/include" "$STAGE/tools" "$STAGE/build" "$STAGE/doc"

# Libraries: whatever this platform managed to build. The manifest printed at
# the end says exactly what made it in, so a kit missing libpfeast says so
# rather than pretending.
cp "$LIBDIR"/libfeast.*   "$STAGE/lib/" 2>/dev/null || true
cp "$LIBDIR"/libspike.a   "$STAGE/lib/" 2>/dev/null || true
cp "$LIBDIR"/libpfeast.a  "$STAGE/lib/" 2>/dev/null || true

cp "$ROOT"/4.0/include/*.h "$STAGE/include/"

# Upstream's examples, unmodified, plus the runners that drive them.
cp -r "$ROOT/4.0/example" "$STAGE/example"
cp "$ROOT"/tools/run_examples.sh "$ROOT"/tools/run_pfeast_examples.sh "$STAGE/tools/"

# The build scripts and the compatibility shims, so the kit can rebuild itself
# (or build PFEAST where CI could not) with the traps already solved.
cp "$ROOT"/build/build-feast.sh "$ROOT"/build/build-spike.sh \
   "$ROOT"/build/build-pfeast.sh "$ROOT"/build/run-test.sh "$STAGE/build/"
cp "$ROOT"/build/spike_blas_compat.f90 "$ROOT"/build/msmpi_inplace_compat.c \
   "$STAGE/build/" 2>/dev/null || true

# The full-feature variant carries MKL's runtime alongside the libraries.
# Intel's Simplified Software License permits redistributing the runtime, and
# "the direct solver exists on this platform" is exactly the feature the
# variant is for -- so the kit must work on a machine with no MKL installed.
if [ -n "${MKL_LIB_DIR:-}" ] && [ -d "${MKL_LIB_DIR}" ]; then
  echo "  bundling MKL runtime from $MKL_LIB_DIR"
  cp "$MKL_LIB_DIR"/libmkl*.dylib "$STAGE/lib/" 2>/dev/null     || cp "$MKL_LIB_DIR"/libmkl*.so* "$STAGE/lib/" 2>/dev/null || true
fi

cp "$ROOT"/BUILDING.md "$ROOT"/BUILDING-COMPLETE.md "$ROOT"/COMPATIBILITY.md \
   "$STAGE/doc/" 2>/dev/null || true
cp "$ROOT"/packaging/README-DEVKIT.md "$STAGE/README.md"

echo "FEAST-devkit-$ARCH contents:"
( cd "$STAGE" && find . -maxdepth 2 -type f | sort | sed 's/^/  /' | head -40 )
echo "  libraries: $(ls "$STAGE/lib" | tr '\n' ' ')"

cd "$ROOT/devkit-stage"
case "$ARCH" in
  windows-*)
    # zip has no executable bit to lose; powershell exists on every runner.
    powershell -NoProfile -Command \
      "Compress-Archive -Path 'FEAST-devkit-$ARCH' -DestinationPath '../FEAST-devkit-$ARCH.zip' -CompressionLevel Optimal"
    OUT="$ROOT/FEAST-devkit-$ARCH.zip" ;;
  *)
    tar czf "../FEAST-devkit-$ARCH.tar.gz" "FEAST-devkit-$ARCH"
    OUT="$ROOT/FEAST-devkit-$ARCH.tar.gz" ;;
esac
ls -lh "$OUT" | awk '{print "devkit: " $NF " (" $5 ")"}'
