#!/usr/bin/env bash
# Build and run FEAST's distributed (PFEAST) examples under MPI.
#
#   bash tools/run_pfeast_examples.sh [arch] [nprocs]
#
# PFEAST parallelises on three levels: L1 (search intervals), L2 (contour
# points) and L3 (the linear system). The example directories are named for the
# levels they exercise. Banded examples are skipped -- they need SPIKE.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
ARCH="${1:-linux-x64}"
NP="${2:-2}"
MPIFC="${MPIFC:-mpif90}"
MPIRUN="${MPIRUN:-mpirun}"
# Open MPI needs --oversubscribe on a small machine; Intel MPI rejects it.
# Note "-" not ":-": an explicitly empty MPIRUN_ARGS must stay empty,
# and ":-" would substitute the default for it.
MPIRUN_ARGS="${MPIRUN_ARGS---oversubscribe}"
# Intel MPI's Hydra rejects -np and wants -n.
NPFLAG="${MPIRUN_NPFLAG:--np}"
# PCsparse_pdfeast_scsrgv_lowest needs well over 10 minutes on 2 ranks.
RUN_TIMEOUT="${RUN_TIMEOUT:-300}"

LIB="$ROOT/4.0/lib/$ARCH/libpfeast.a"
INC="$ROOT/4.0/include"
BLAS="${BLAS_LIBS:--lopenblas}"

[ -f "$LIB" ] || { echo "no $LIB -- run build/build-pfeast.sh first" >&2; exit 1; }
command -v "$MPIRUN" >/dev/null || { echo "no $MPIRUN on PATH" >&2; exit 1; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

pass=0; fail=0; skip=0
declare -a FAILED=()
echo "Running PFEAST examples against $LIB with $NP processes"
echo

for dir in "$ROOT"/4.0/example/PFEAST-*; do
  [ -d "$dir" ] || continue
  echo "--- $(basename "$dir") ---"
  cp "$dir"/*.mtx "$WORK"/ 2>/dev/null || true
  for src in "$dir"/*.c "$dir"/*.f90; do
    [ -e "$src" ] || continue
    name="$(basename "$src")"; base="${name%.*}"
    case "$base" in
      *banded*) echo "  SKIP  $name  (needs SPIKE)"; skip=$((skip+1)); continue ;;
    esac

    bin="$WORK/$base"
    if [[ "$name" == *.c ]]; then
      mpicc -O2 -c "$src" -o "$bin.o" -I"$INC" 2>"$WORK/$base.build" \
        && "$MPIFC" -o "$bin" "$bin.o" "$LIB" $BLAS -fopenmp -lm 2>>"$WORK/$base.build"
    else
      "$MPIFC" -O2 -ffree-line-length-none -o "$bin" "$src" "$LIB" $BLAS -fopenmp \
        2>"$WORK/$base.build"
    fi
    if [ ! -x "$bin" ]; then
      echo "  BUILD-FAIL  $name"; sed 's/^/        /' "$WORK/$base.build" | tail -3
      FAILED+=("$name (build)"); fail=$((fail+1)); continue
    fi

    # How each directory expects to be launched, per its own README:
    #   PFEAST-L2      contour-point parallelism only; takes no argument
    #   PFEAST-L2L3    argv[1] is how many ranks go to level 3. Omitting it
    #                  makes the program divide by zero and die on SIGFPE.
    #   PFEAST-L1L2L3  two search intervals x L2 x L3, so it wants 8 ranks
    case "$(basename "$dir")" in
      PFEAST-L2L3)   np="$NP"; arg="$NP" ;;
      PFEAST-L1L2L3) np=8;     arg=2 ;;
      *)             np="$NP"; arg="" ;;
    esac

    out="$WORK/$base.out"
    if (cd "$WORK" && timeout "$RUN_TIMEOUT" "$MPIRUN" $NPFLAG "$np" $MPIRUN_ARGS "./$base" $arg \
          >"$out" 2>&1); then
      if grep -qiE "info *[:=] *[^0 ]|FEAST OUTPUT INFO +[^0 ]" "$out"; then
        echo "  RAN-BAD-INFO  $name"; grep -iE "info" "$out" | head -2 | sed 's/^/        /'
        FAILED+=("$name (info)"); fail=$((fail+1))
      else
        echo "  PASS  $name"; pass=$((pass+1))
      fi
    else
      echo "  RUN-FAIL  $name"; tail -3 "$out" | sed 's/^/        /'
      FAILED+=("$name (run)"); fail=$((fail+1))
    fi
  done
done

echo
echo "passed $pass, failed $fail, skipped $skip"
[ ${#FAILED[@]} -gt 0 ] && printf '  failed: %s\n' "${FAILED[@]}"
[ "$fail" -eq 0 ]
