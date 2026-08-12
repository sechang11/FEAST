"""Check FEAST's C headers against the Fortran they declare.

    python tools/check_headers.py [path-to-4.0]

FEAST is written in Fortran. The C headers in 4.0/include exist so that C
programs can call those Fortran routines directly, and they are hand-maintained
-- nothing verifies that a prototype still matches the subroutine it names.

When they disagree in argument *count*, the consequences are not a compiler
error. Fortran passes everything by reference, so a C caller pushes N pointers
and the Fortran reads N+1; the extra one is whatever happened to be next in the
register or on the stack. Arguments after the missing one shift by one
position, so an integer gets read as a pointer or a pointer as an integer, and
if the shifted arguments are *outputs* the callee writes through an address the
caller never supplied. That is memory corruption, and it happens silently.

This script compares every `extern void name_(...)` prototype with the
`subroutine name(...)` it refers to and reports any disagreement. Run it in CI
so a hand-edited header cannot regress.

Exit status is 0 when everything matches, 1 otherwise.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1
            else Path(__file__).resolve().parent.parent / "4.0")

# Mismatches already reported upstream and worked around in feastpy/raw.py
# (_HEADER_CORRECTIONS). Listed so this script stays useful as a regression
# check without failing the build over known, handled bugs. Remove an entry
# when a FEAST release fixes it.
KNOWN = {
    "zfeast_gcontour", "cfeast_gcontour",
    "zfeast_grational", "cfeast_grational",
}


def _split(args: str) -> list[str]:
    return [a.strip() for a in args.split(",") if a.strip()]


def fortran_subroutines(root: Path) -> dict:
    out: dict = {}
    for f in (root / "src").rglob("*.f90"):
        text = f.read_text(errors="replace")
        for m in re.finditer(r"^\s*subroutine\s+(\w+)\s*\(([^)]*)\)", text, re.M | re.I):
            out.setdefault(m.group(1).lower(), (_split(m.group(2)), f.name))
    return out


def c_prototypes(root: Path) -> dict:
    out: dict = {}
    for h in sorted((root / "include").glob("*.h")):
        text = h.read_text(errors="replace")
        # `extern void name_(...);` -- the trailing underscore is gfortran's
        # symbol mangling, so strip it to get the Fortran name.
        for m in re.finditer(r"extern\s+void\s+(\w+?)_\s*\(([^)]*)\)\s*;", text):
            out[m.group(1).lower()] = (_split(m.group(2)), h.name)
    return out


def main() -> int:
    if not (ROOT / "include").is_dir():
        print(f"no FEAST tree at {ROOT}", file=sys.stderr)
        return 2

    fort = fortran_subroutines(ROOT)
    proto = c_prototypes(ROOT)

    compared = new = known = 0
    for name, (cargs, hfile) in sorted(proto.items()):
        if name not in fort:
            continue                      # RCI helpers, aliases, etc.
        fargs, ffile = fort[name]
        compared += 1
        if len(cargs) == len(fargs):
            continue
        tag = "KNOWN" if name in KNOWN else "NEW"
        if name in KNOWN:
            known += 1
        else:
            new += 1
        print(f"[{tag}] {name}_  C declares {len(cargs)}, Fortran defines {len(fargs)}")
        print(f"       C   ({hfile}): {', '.join(a.split()[-1].lstrip('*') for a in cargs)}")
        print(f"       F90 ({ffile}): {', '.join(fargs)}")

    print(f"\ncompared {compared} routines declared in both C and Fortran: "
          f"{new} new mismatch(es), {known} known")
    if new:
        print("A C caller of the above corrupts memory; see raw.py's "
              "_HEADER_CORRECTIONS for the pattern used to work around them.")
    return 1 if new else 0


if __name__ == "__main__":
    raise SystemExit(main())
