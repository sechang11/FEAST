"""Locating and loading the native FEAST shared library.

The GUI, the CLI and the web backend all go through this module, so there is
exactly one place that knows where the binary lives and how its symbols are
spelled.
"""
from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

_OS_TAGS = {"win32": "windows", "darwin": "macos", "linux": "linux"}

# platform.machine() is not normalized across OSes: Windows says AMD64, Linux
# says x86_64, macOS says arm64 and Linux says aarch64 for the same chip.
_MACH_TAGS = {
    "amd64": "x64", "x86_64": "x64", "x64": "x64",
    "arm64": "arm64", "aarch64": "arm64",
}

_SONAME = {"win32": "libfeast.dll", "darwin": "libfeast.dylib"}


def _candidate_paths() -> list[Path]:
    """Search order: explicit override, bundled (frozen app), then dev tree."""
    name = _SONAME.get(sys.platform, "libfeast.so")
    here = Path(__file__).resolve().parent
    out: list[Path] = []

    override = os.environ.get("FEAST_LIBRARY")
    if override:
        out.append(Path(override))

    # PyInstaller / py2app lay the library down next to the executable.
    if getattr(sys, "frozen", False):
        out.append(Path(sys._MEIPASS) / name)  # type: ignore[attr-defined]
        out.append(Path(sys.executable).parent / name)

    out.append(here / "_native" / name)  # wheel layout

    import platform
    os_tag = _OS_TAGS.get(sys.platform, "linux")
    mach_tag = _MACH_TAGS.get(platform.machine().lower(), "x64")
    out.append(here / ".." / ".." / "4.0" / "lib" / f"{os_tag}-{mach_tag}" / name)

    return out


class FeastLibraryNotFound(RuntimeError):
    pass


_lib: ctypes.CDLL | None = None


def load() -> ctypes.CDLL:
    """Load (and cache) libfeast. Raises FeastLibraryNotFound with the paths tried."""
    global _lib
    if _lib is not None:
        return _lib

    tried = []
    for p in _candidate_paths():
        p = p.resolve() if p.exists() else p
        tried.append(str(p))
        if not p.exists():
            continue
        # On Windows the DLL pulls in libopenblas/libgfortran from the mingw
        # bin directory; add whatever directory it lives in to the search path.
        if sys.platform == "win32" and hasattr(os, "add_dll_directory"):
            # libfeast.dll pulls in libopenblas and libgfortran from the mingw
            # bin directory. Since Python 3.8 that directory has to be declared
            # explicitly -- PATH alone is not consulted for dependent DLLs.
            extras = [str(p.parent)]
            # FEAST_DLL_DIR covers installs that are not at the default path,
            # e.g. GitHub's runners, which put MSYS2 under RUNNER_TEMP.
            extras += [d for d in os.environ.get("FEAST_DLL_DIR", "").split(os.pathsep) if d]
            extras.append(r"C:\msys64\mingw64\bin")
            for extra in extras:
                if extra and Path(extra).is_dir():
                    try:
                        os.add_dll_directory(extra)
                    except OSError:
                        pass
        _lib = ctypes.CDLL(str(p))
        return _lib

    raise FeastLibraryNotFound(
        "could not locate libfeast. Tried:\n  " + "\n  ".join(tried)
        + "\n\nBuild it with build/build-feast.sh, or set FEAST_LIBRARY to its path."
    )


def sym(name: str):
    """Fetch a Fortran symbol. gfortran/ifort lowercase and append one underscore."""
    return getattr(load(), name + "_")
