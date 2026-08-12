"""Direct, typed access to every FEAST routine in the shipped library.

The high-level functions in `solver` cover the common problems ergonomically.
This module covers *everything else*: the signatures are parsed out of FEAST's
own C headers, so any declared routine can be called with correct marshalling
without hand-writing a wrapper for each of the 200-odd entry points.

    from feastpy import raw
    raw.signature("dfeast_gcsrgv")        # argument names and types
    raw.call("dfeast_gcsrgv", N=n, sa=..., fpm=fpm, ...)

Scalars are passed by reference (Fortran's convention), arrays as pointers to
their buffers. Every argument in the signature must be supplied; FEAST writes
its outputs into the arrays you pass, which is also how you get results back.
"""
from __future__ import annotations

import ctypes
import re
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np

from . import _lib

_CTYPES = {
    "char": ctypes.c_char,
    "int": ctypes.c_int,
    "float": ctypes.c_float,
    "double": ctypes.c_double,
}

# numpy dtype expected for an array argument of each C type
_DTYPES = {
    "int": np.int32,
    "float": np.float32,
    "double": np.float64,
    "char": np.uint8,
}

_DECL = re.compile(r"extern\s+void\s+([a-z_0-9]+)_\s*\(([^)]*)\)\s*;", re.S)
_ARG = re.compile(r"^\s*(char|int|float|double)\s*\*\s*([A-Za-z_0-9]+)\s*$")


def _header_dir() -> Path:
    """Where FEAST's headers live, including inside a frozen app."""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        for cand in (base / "feast_include", base / "4.0" / "include"):
            if cand.is_dir():
                return cand
    return Path(__file__).resolve().parent.parent.parent / "4.0" / "include"


# Routines whose C header declaration disagrees with the Fortran that actually
# runs. FEAST 4.0's include/feast_tools.h omits the fpm18 argument (the ellipse
# ratio) from four of the non-Hermitian contour utilities, declaring seven
# arguments where src/kernel/feast_tools.f90 defines eight:
#
#   header:  zfeast_gcontour_(Emid, r, fpm2, fpm17,        fpm19, Zne, Wne)
#   Fortran: zfeast_gcontour (Emid, r, fpm8, fpm17, fpm18, fpm19, Zne, Wne)
#
# Calling these as declared shifts every argument after fpm17 by one, so the
# rotation angle is read from the ellipse-ratio slot, an *address* is read as
# the rotation angle, and the Zne/Wne output pointers are read from past the
# end of the supplied arguments -- writes to whatever those bytes happen to be.
# That is memory corruption, not merely a wrong answer, and it affects any C
# caller. Verified against the Fortran source and by calling both forms; with
# the eight-argument form a radius-1 circular contour puts every node at
# distance 1.000000 from the centre, and fpm18=30 correctly flattens it.
#
# Reported upstream (see PLAIN-ENGLISH.md). Corrected here so the shipped
# library stays usable; the fix is to the *declaration*, not to FEAST.
_HEADER_CORRECTIONS: dict[str, list[tuple[str, str]]] = {
    name: [(t, "Emid"), (t, "r"), ("int", "fpm8"), ("int", "fpm17"),
           ("int", "fpm18"), ("int", "fpm19")] + tail
    for name, t, tail in (
        ("zfeast_gcontour",  "double", [("double", "Zne"), ("double", "Wne")]),
        ("cfeast_gcontour",  "float",  [("float",  "Zne"), ("float",  "Wne")]),
        ("zfeast_grational", "double", [("double", "Eig"), ("int", "M0"),
                                        ("double", "f")]),
        ("cfeast_grational", "float",  [("float",  "Eig"), ("int", "M0"),
                                        ("float",  "f")]),
    )
}


@lru_cache(maxsize=1)
def signatures() -> dict[str, list[tuple[str, str]]]:
    """{routine: [(ctype, argument name), ...]} parsed from the headers."""
    out: dict[str, list[tuple[str, str]]] = {}
    hdr = _header_dir()
    if not hdr.is_dir():
        return out
    for h in sorted(hdr.glob("*.h")):
        text = h.read_text(errors="replace")
        for name, arglist in _DECL.findall(text):
            args = []
            ok = True
            for chunk in arglist.split(","):
                m = _ARG.match(chunk)
                if not m:
                    ok = False
                    break
                args.append((m.group(1), m.group(2)))
            if ok and name not in out:
                out[name] = args
    out.update(_HEADER_CORRECTIONS)
    return out


def signature(name: str) -> list[tuple[str, str]]:
    sig = signatures().get(name)
    if sig is None:
        raise KeyError(f"{name} is not declared in FEAST's headers")
    return sig


def available() -> list[str]:
    """Routines that are declared *and* present in the library we ship.

    The difference is not an oversight: the banded interfaces need SPIKE and
    PFEAST needs MPI, and neither is bundled, so those symbols are absent.
    """
    lib = _lib.load()
    found = []
    for name in signatures():
        try:
            getattr(lib, name + "_")
            found.append(name)
        except AttributeError:
            pass
    return sorted(found)


def is_available(name: str) -> bool:
    try:
        getattr(_lib.load(), name + "_")
        return True
    except AttributeError:
        return False


def _as_arg(ctype: str, value):
    """Marshal one argument. Arrays pass their buffer, scalars pass a pointer."""
    if isinstance(value, np.ndarray):
        want = _DTYPES[ctype]
        if value.dtype == np.complex128 and ctype == "double":
            pass                      # complex arrays are pairs of doubles
        elif value.dtype == np.complex64 and ctype == "float":
            pass
        elif value.dtype != want:
            raise TypeError(
                f"expected a {np.dtype(want).name} array for a {ctype}* argument, "
                f"got {value.dtype}")
        if not value.flags["F_CONTIGUOUS"] and not value.flags["C_CONTIGUOUS"]:
            raise TypeError("array must be contiguous")
        return value.ctypes.data_as(ctypes.c_void_p), None

    if ctype == "char":
        buf = ctypes.c_char(str(value).encode()[:1])
        return ctypes.byref(buf), buf
    cval = _CTYPES[ctype](value)
    return ctypes.byref(cval), cval


def call(name: str, **kwargs):
    """Call a FEAST routine by name with keyword arguments from its signature.

    Returns a dict of the scalar arguments after the call, so `info`, `mode`,
    `loop` and `epsout` come back without the caller juggling ctypes objects.
    """
    sig = signature(name)
    if not is_available(name):
        raise RuntimeError(
            f"{name} is declared but not present in this build of libfeast. "
            "Banded routines need the SPIKE solver and PFEAST needs MPI; "
            "neither is bundled. See COVERAGE.md.")

    expected = [a for _, a in sig]
    missing = [a for a in expected if a not in kwargs]
    if missing:
        raise TypeError(f"{name} needs {missing}; signature is "
                        + ", ".join(f"{t}* {a}" for t, a in sig))
    extra = [k for k in kwargs if k not in expected]
    if extra:
        raise TypeError(f"{name} has no argument(s) {extra}")

    args, keep = [], {}
    for ctype, argname in sig:
        ptr, holder = _as_arg(ctype, kwargs[argname])
        args.append(ptr)
        if holder is not None:
            keep[argname] = holder

    getattr(_lib.load(), name + "_")(*args)
    return {k: (v.value.decode() if isinstance(v, ctypes.c_char) else v.value)
            for k, v in keep.items()}


def new_fpm(**overrides) -> np.ndarray:
    """A parameter array initialised by FEAST, with fpm(N) given as fpm_N.

    The documentation uses Fortran's 1-based fpm(1..64); this keeps that naming
    so settings can be copied straight out of the user guide.
    """
    fpm = np.zeros(64, dtype=np.int32)
    _lib.sym("feastinit")(fpm.ctypes.data_as(ctypes.POINTER(ctypes.c_int)))
    for key, value in overrides.items():
        m = re.fullmatch(r"fpm_(\d+)", key)
        if not m:
            raise TypeError(f"expected fpm_<n>, got {key!r}")
        idx = int(m.group(1))
        if not 1 <= idx <= 64:
            raise ValueError(f"fpm index out of range: {idx}")
        fpm[idx - 1] = int(value)
    return fpm
