# PyInstaller spec for the FEAST desktop app.
#
#   pyinstaller packaging/feast.spec --noconfirm
#
# Produces a self-contained folder in dist/ that runs with no Python installed.
# The tricky parts are the native pieces: libfeast itself, and on Windows the
# mingw runtime it links (OpenBLAS, libgfortran, libquadmath, libwinpthread),
# which PyInstaller cannot discover because ctypes loads the library by path at
# runtime rather than importing it.

import os
import platform
import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent
sys.path.insert(0, str(ROOT / "python"))

OS_TAG = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
MACH_TAG = {"amd64": "x64", "x86_64": "x64", "arm64": "arm64",
            "aarch64": "arm64"}.get(platform.machine().lower(), "x64")
ARCH = f"{OS_TAG}-{MACH_TAG}"
LIBDIR = ROOT / "4.0" / "lib" / ARCH
SONAME = {"windows": "libfeast.dll", "macos": "libfeast.dylib"}.get(OS_TAG, "libfeast.so")

libfeast = LIBDIR / SONAME
if not libfeast.exists():
    raise SystemExit(
        f"{libfeast} not found -- run build/build-feast.sh first")

# feastpy looks beside the executable, then in _MEIPASS; '.' satisfies both.
binaries = [(str(libfeast), ".")]

# Windows: ship the mingw runtime next to libfeast.dll. Without these the app
# starts and then fails to load the solver on a machine that has no MSYS2.
if OS_TAG == "windows":
    mingw = Path(os.environ.get("MINGW_BIN", r"C:\msys64\mingw64\bin"))
    wanted = ("libopenblas", "libgfortran", "libquadmath", "libwinpthread",
              "libgcc_s_seh", "libgomp", "libstdc++")
    if mingw.is_dir():
        for dll in mingw.glob("*.dll"):
            if dll.name.startswith(wanted):
                binaries.append((str(dll), "."))
    else:
        print(f"WARNING: {mingw} not found; the bundle may not load libfeast")

# FEAST's sample matrices back the built-in problems. Ship all of them, so the
# catalogue in feastpy/problems.py is not full of entries that vanish once the
# app is packaged. That includes the 68 MB benzene pair: it compresses well and
# a scientific application is downloaded once.
datas = []
for src in (ROOT / "4.0" / "utility" / "data",
            # system5's three matrices (the quadratic polynomial problem) live
            # here rather than in utility/data.
            ROOT / "4.0" / "example" / "FEAST"):
    for f in sorted(src.glob("*.mtx")):
        datas.append((str(f), "feast_data"))
print(f"bundling {len(datas)} sample matrices "
      f"({sum(Path(d[0]).stat().st_size for d in datas) / 1048576:.0f} MB)")

a = Analysis(
    [str(ROOT / "gui" / "app.py")],
    pathex=[str(ROOT / "python"), str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=[
        "feastpy", "feastpy._solve_child", "feastpy.runner",
        "feastpy.codegen", "feastpy.diagnostics", "feastpy.matrixio",
        "feastpy.results_io", "feastpy.solver",
        "scipy.io", "scipy.sparse.linalg", "scipy.spatial.transform._rotation",
        "licensing", "licensing.keys", "licensing.machine",
        "cryptography.hazmat.primitives.asymmetric.ed25519",
    ],
    excludes=[
        # Qt modules the app never touches; they roughly double the bundle.
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
        "PySide6.QtQuick", "PySide6.QtQml", "PySide6.Qt3DCore",
        "PySide6.QtMultimedia", "PySide6.QtDesigner", "PySide6.QtCharts",
        "PySide6.QtDataVisualization", "PySide6.QtBluetooth",
        "matplotlib", "tkinter", "pytest", "IPython",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="FEAST",
    console=False,          # a GUI app; --selftest still prints on Windows via
                            # the parent console when run from a terminal
    icon=None,
)

coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=False,
    name=f"FEAST-{ARCH}",
)

if OS_TAG == "macos":
    app = BUNDLE(
        coll,
        name="FEAST.app",
        bundle_identifier="org.feast-solver.desktop",
        info_plist={
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
            "CFBundleShortVersionString": "4.0.0",
        },
    )
