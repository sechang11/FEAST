"""Map every FEAST entry point against what feastpy can reach.

    python tools/coverage_report.py [--markdown]

Cross-references three things:
  * what the C headers declare (the documented API surface),
  * what the shared library we ship actually exports,
  * what feastpy exposes.

The gap between the second and third is work to do; the gap between the first
and second is work that cannot be done without something we do not ship
(SPIKE for the banded interfaces, MPI and libpfeast for PFEAST).
"""
from __future__ import annotations

import ctypes
import platform
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))


def family(name: str) -> str:
    if name.startswith("p") and "feast" in name and not name.startswith("pdz"):
        return "PFEAST (MPI)"
    if "rci" in name:
        return "RCI"
    if "pev" in name:
        return "polynomial"
    if re.search(r"(gb|sb|hb)[a-z]*v", name):
        return "banded"
    if "csr" in name:
        return "sparse CSR"
    if re.search(r"g(e|c)", name) and "feast_g" in name:
        return "non-Hermitian"
    if re.search(r"feast_(sy|he)", name):
        return "dense Hermitian"
    return "tools/contours"


def declared() -> set[str]:
    names = set()
    for h in (ROOT / "4.0" / "include").glob("*.h"):
        for m in re.finditer(r"extern void ([a-z_0-9]+)_\(", h.read_text(errors="replace")):
            names.add(m.group(1))
    return names


def exported() -> set[str]:
    """Symbols the shared library we ship actually provides."""
    os_tag = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
    mach = {"amd64": "x64", "x86_64": "x64", "arm64": "arm64",
            "aarch64": "arm64"}.get(platform.machine().lower(), "x64")
    soname = {"windows": "libfeast.dll", "macos": "libfeast.dylib"}.get(os_tag, "libfeast.so")
    lib_path = ROOT / "4.0" / "lib" / f"{os_tag}-{mach}" / soname
    if not lib_path.exists():
        print(f"note: {lib_path} not found; reporting declarations only\n")
        return set()

    import feastpy
    lib = feastpy.load()
    found = set()
    for n in declared():
        try:
            getattr(lib, n + "_")
            found.add(n)
        except AttributeError:
            pass
    return found


def reachable() -> set[str]:
    """What feastpy can call today.

    Everything the library exports is callable through feastpy.raw, which builds
    its calls from the header signatures rather than hand-written wrappers.
    """
    from feastpy import raw
    return set(raw.available())


def wrapped() -> set[str]:
    """Routines with an ergonomic wrapper, as opposed to raw access."""
    names = {"feastinit"}
    for p in ("d", "z"):
        for k in ("sy", "he", "ge"):
            for t in ("ev", "gv"):
                names.add(f"{p}feast_{k}{t}")
    for t in ("ev", "gv"):
        names.add(f"difeast_scsr{t}")
        names.add(f"dfeast_gcsr{t}")
        names.add(f"zfeast_scsr{t}")
    return names


def main() -> int:
    dec, exp, reach = declared(), exported(), reachable()
    fams: dict[str, list[int]] = {}
    for n in sorted(dec):
        f = family(n)
        row = fams.setdefault(f, [0, 0, 0])
        row[0] += 1
        if n in exp:
            row[1] += 1
        if n in reach:
            row[2] += 1

    md = "--markdown" in sys.argv
    print(f"FEAST entry points declared in headers: {len(dec)}")
    print(f"  exported by the library we ship     : {len(exp)}")
    print(f"  reachable from feastpy              : {len(dec & reach)}\n")

    if md:
        print("| Family | Declared | In our library | In feastpy |")
        print("|---|---:|---:|---:|")
    else:
        print(f"{'family':22} {'declared':>9} {'in lib':>8} {'feastpy':>8}")
    for f, (d, e, r) in sorted(fams.items(), key=lambda kv: -kv[1][0]):
        if md:
            print(f"| {f} | {d} | {e} | {r} |")
        else:
            print(f"{f:22} {d:>9} {e:>8} {r:>8}")

    wrap = wrapped()
    print(f"\nwith an ergonomic wrapper: {len(exp & wrap)} of {len(exp)}")

    absent = sorted(dec - exp)
    why = {"banded": "needs SPIKE, not bundled",
           "PFEAST (MPI)": "needs MPI and libpfeast, not built"}
    print(f"\nDeclared but absent from this build ({len(absent)}):")
    for f in sorted({family(n) for n in absent}):
        names = [n for n in absent if family(n) == f]
        print(f"  {f:22} {len(names):>3}  ({why.get(f, 'not built')})")

    raw_only = sorted(exp - wrap)
    print(f"\nCallable through raw, no ergonomic wrapper yet ({len(raw_only)}):")
    for f in sorted({family(n) for n in raw_only}):
        names = [n for n in raw_only if family(n) == f]
        print(f"  {f:22} {len(names):>3}  e.g. {', '.join(names[:3])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
