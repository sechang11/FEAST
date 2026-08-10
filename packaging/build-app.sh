#!/usr/bin/env bash
# Build the standalone desktop app for this platform.
#
#   bash packaging/build-app.sh
#
# Requires libfeast to be built already (build/build-feast.sh) and the Python
# dependencies installed. Output lands in dist/FEAST-<os>-<arch>/.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
PY="${PYTHON:-python}"

case "$(uname -s)" in
  Linux)        OS=linux ;;
  Darwin)       OS=macos ;;
  MINGW*|MSYS*) OS=windows
                export TMPDIR="${TMPDIR:-C:/feasttmp}"
                export TMP="$TMPDIR" TEMP="$TMPDIR"; mkdir -p "$TMPDIR"
                # The spec copies the mingw runtime from here; without it the
                # bundle starts but cannot load the solver on a clean machine.
                export MINGW_BIN="${MINGW_BIN:-C:/msys64/mingw64/bin}" ;;
  *) echo "unsupported platform: $(uname -s)" >&2; exit 1 ;;
esac
case "$(uname -m)" in arm64|aarch64) MACH=arm64 ;; *) MACH=x64 ;; esac
ARCH="$OS-$MACH"

LIB="$ROOT/4.0/lib/$ARCH"
if ! ls "$LIB"/libfeast.* >/dev/null 2>&1; then
  echo "no libfeast in $LIB -- run build/build-feast.sh first" >&2
  exit 1
fi

cd "$ROOT"
"$PY" -m PyInstaller packaging/feast.spec --noconfirm \
      --distpath dist --workpath build/pyi

OUT="$ROOT/dist/FEAST-$ARCH"
echo
echo "built: $OUT"
du -sh "$OUT" 2>/dev/null || true

# Prove it works without the build environment: a bundle that only runs on the
# machine that built it is worthless.
echo
echo "self-test (clean environment):"
if [ "$OS" = macos ] && [ -d "$ROOT/dist/FEAST.app" ]; then
  BIN="$ROOT/dist/FEAST.app/Contents/MacOS/FEAST"
else
  BIN="$OUT/FEAST"
  [ "$OS" = windows ] && BIN="$OUT/FEAST.exe"
fi

cd "$OUT"
if [ "$OS" = windows ]; then
  FEAST_SELFTEST_OUT=selftest.txt "$BIN" --selftest || true
  cat selftest.txt
  grep -q "SELFTEST PASS" selftest.txt
else
  env -i HOME="$HOME" PATH=/usr/bin:/bin QT_QPA_PLATFORM=offscreen \
      "$BIN" --selftest | tee selftest.txt
  grep -q "SELFTEST PASS" selftest.txt
fi
echo "OK"
