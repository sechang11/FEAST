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
FC="${FC:-gfortran}"

case "$(uname -s)" in
  Linux)  OS=linux;  BLAS="${BLAS_LIBS:--lopenblas}" ;;
  Darwin) OS=macos;  BLAS="${BLAS_LIBS:--L$(brew --prefix openblas)/lib -lopenblas}" ;;
  MINGW*|MSYS*) OS=windows; BLAS="${BLAS_LIBS:--lopenblas}"
                export TMPDIR="${TMPDIR:-C:/feasttmp}"; export TMP="$TMPDIR" TEMP="$TMPDIR"; mkdir -p "$TMPDIR" ;;
esac
case "$(uname -m)" in arm64|aarch64) MACH=arm64 ;; *) MACH=x64 ;; esac
ARCH="${1:-$OS-$MACH}"
LIB="$ROOT/4.0/lib/$ARCH/libfeast.a"
INC="$ROOT/4.0/include"
EX="$ROOT/4.0/example/FEAST"

[ -f "$LIB" ] || { echo "no $LIB -- run build/build-feast.sh first" >&2; exit 1; }

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
    *banded*|P*) echo "  SKIP  $name  (needs SPIKE)"; skip=$((skip+1)); continue ;;
  esac

  bin="$WORK/$base"
  if [[ "$name" == *.c ]]; then
    # Compile with cc, link with the Fortran driver: Apple's clang rejects
    # -fopenmp and does not know where libgfortran lives.
    cc -O2 -c "$src" -o "$bin.o" -I"$INC" 2>"$WORK/$base.build" \
      && "$FC" -o "$bin" "$bin.o" "$LIB" $BLAS -fopenmp -lm 2>>"$WORK/$base.build"
  else
    "$FC" -O2 -ffree-line-length-none -o "$bin" "$src" "$LIB" $BLAS -fopenmp 2>"$WORK/$base.build"
  fi

  if [ ! -x "$bin" ]; then
    echo "  BUILD-FAIL  $name"
    sed 's/^/        /' "$WORK/$base.build" | tail -3
    FAILED+=("$name (build)"); fail=$((fail+1)); continue
  fi

  # The examples read their matrices from the working directory.
  out="$WORK/$base.out"
  if (cd "$WORK" && timeout 300 "./$base" >"$out" 2>&1); then
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
