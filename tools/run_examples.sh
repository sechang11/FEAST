#!/usr/bin/env bash
# Build and run FEAST's own example programs against the library we produce.
#
#   bash tools/run_examples.sh [arch]
#
# The point is not the examples themselves -- it is that upstream's own
# programs, unmodified, work against our build. That is a much stronger claim
# than "our tests pass".
#
# Banded examples are skipped: they need SPIKE, which upstream does not bundle.
# PFEAST examples are skipped: they need MPI and libpfeast, which we do not build.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
# Run from the repository or from inside a Developer Kit: the repo keeps
# everything under 4.0/, the kit flattens to lib/ example/ include/. Detect
# rather than assume, so the kit can test itself on a machine with no repo.
if [ -d "$ROOT/4.0" ]; then BASE="$ROOT/4.0"; else BASE="$ROOT"; fi
FC="${FC:-gfortran}"

case "$(uname -s)" in
  Linux)  OS=linux;  BLAS="${BLAS_LIBS:--lopenblas}" ;;
  Darwin) OS=macos;  BLAS="${BLAS_LIBS:--L$(brew --prefix openblas)/lib -lopenblas}" ;;
  MINGW*|MSYS*) OS=windows; BLAS="${BLAS_LIBS:--lopenblas}"
                export TMPDIR="${TMPDIR:-C:/feasttmp}"; export TMP="$TMPDIR" TEMP="$TMPDIR"; mkdir -p "$TMPDIR" ;;
esac
case "$(uname -m)" in arm64|aarch64) MACH=arm64 ;; *) MACH=x64 ;; esac
ARCH="${1:-$OS-$MACH}"
LIB="$BASE/lib/$ARCH/libfeast.a"
INC="$BASE/include"
EX="$BASE/example/FEAST"

[ -f "$LIB" ] || { echo "no $LIB -- run build/build-feast.sh first" >&2; exit 1; }

# Banded needs SPIKE. If a libspike.a sits beside libfeast.a, run those too.
SPIKE="$BASE/lib/$ARCH/libspike.a"
if [ -f "$SPIKE" ]; then
  SPIKE_LINK="$SPIKE"
  echo "SPIKE found: banded examples will be attempted"
else
  SPIKE_LINK=""
fi

# `timeout` is GNU coreutils and does not exist on macOS, where every example
# then "fails" with exit 127. Use gtimeout if the user has coreutils, else fall
# back to a watchdog: run in the background, kill it if it outstays its welcome.
if command -v timeout >/dev/null 2>&1;  then RUN_LIMITED() { timeout "$@"; }
elif command -v gtimeout >/dev/null 2>&1; then RUN_LIMITED() { gtimeout "$@"; }
else
  RUN_LIMITED() {
    local secs="$1"; shift
    "$@" & local pid=$!
    ( sleep "$secs"; kill -9 "$pid" 2>/dev/null ) & local watchdog=$!
    wait "$pid"; local rc=$?
    kill "$watchdog" 2>/dev/null; wait "$watchdog" 2>/dev/null
    return $rc
  }
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
cp "$EX"/*.mtx "$WORK"/ 2>/dev/null || true

pass=0; fail=0; skip=0
declare -a FAILED=()

echo "Running FEAST's own examples against $LIB"
echo

for src in "$EX"/*.c "$EX"/*.f90; do
  name="$(basename "$src")"
  base="${name%.*}"

  # Banded needs SPIKE; PFEAST needs MPI. Neither is bundled.
  case "$base" in
    *banded*)
      if [ -z "$SPIKE_LINK" ]; then
        echo "  SKIP  $name  (needs SPIKE)"; skip=$((skip+1)); continue
      fi ;;
    P*) echo "  SKIP  $name  (PFEAST: needs MPI)"; skip=$((skip+1)); continue ;;
  esac

  bin="$WORK/$base"
  if [[ "$name" == *.c ]]; then
    # Compile with cc, link with the Fortran driver: Apple's clang rejects
    # -fopenmp and does not know where libgfortran lives.
    cc -O2 -c "$src" -o "$bin.o" -I"$INC" 2>"$WORK/$base.build" \
      && "$FC" -o "$bin" "$bin.o" "$LIB" $SPIKE_LINK $BLAS -fopenmp -lm 2>>"$WORK/$base.build"
  else
    "$FC" -O2 -ffree-line-length-none -o "$bin" "$src" "$LIB" $SPIKE_LINK $BLAS -fopenmp       2>"$WORK/$base.build"
  fi

  if [ ! -x "$bin" ]; then
    echo "  BUILD-FAIL  $name"
    sed 's/^/        /' "$WORK/$base.build" | tail -3
    FAILED+=("$name (build)"); fail=$((fail+1)); continue
  fi

  # The examples read their matrices from the working directory.
  out="$WORK/$base.out"
  if (cd "$WORK" && RUN_LIMITED 300 "./$base" >"$out" 2>&1); then
    # FEAST prints "info" -- a nonzero value means it ran but did not succeed.
    if grep -qiE "info *[:=] *[^0 ]|FEAST OUTPUT INFO +[^0 ]" "$out"; then
      echo "  RAN-BAD-INFO  $name"
      grep -iE "info" "$out" | head -2 | sed 's/^/        /'
      FAILED+=("$name (info)"); fail=$((fail+1))
    else
      echo "  PASS  $name"
      pass=$((pass+1))
    fi
  else
    echo "  RUN-FAIL  $name  (exit $?)"
    tail -3 "$out" | sed 's/^/        /'
    FAILED+=("$name (run)"); fail=$((fail+1))
  fi
done

echo
echo "passed $pass, failed $fail, skipped $skip"
if [ ${#FAILED[@]} -gt 0 ]; then
  printf '  failed: %s\n' "${FAILED[@]}"
fi
[ "$fail" -eq 0 ]
