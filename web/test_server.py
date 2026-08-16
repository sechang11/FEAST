"""Tests for the web API.

    python test_server.py            (from this directory)

The calculator has two search regions and the wrong one is not an error -- it
is a full set of plausible wrong numbers. That is what most of this file is
about: which region a request gets, and whether a matrix is allowed into it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "python"))
sys.path.insert(0, str(HERE))

from fastapi.testclient import TestClient      # noqa: E402

import server                                  # noqa: E402

client = TestClient(server.app)

passed = failed = 0


def check(name: str, cond: bool, note: str = "") -> None:
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS  {name}" + (f"  {note}" if note else ""))
    else:
        failed += 1
        print(f"  FAIL  {name}" + (f"  {note}" if note else ""))


def dense_mtx(M) -> str:
    n = M.shape[0]
    rows = ["%%MatrixMarket matrix array real general", f"{n} {n}"]
    for j in range(n):
        for i in range(n):
            rows.append(repr(float(M[i, j])))
    return "\n".join(rows)


def grcar(n: int = 60):
    G = np.eye(n) + np.diag([-1.0] * (n - 1), -1)
    for k in (1, 2, 3):
        G = G + np.diag([1.0] * (n - k), k)
    return G


def laplacian(n: int = 40):
    return (np.diag([2.0] * n) + np.diag([-1.0] * (n - 1), 1)
            + np.diag([-1.0] * (n - 1), -1))


GRCAR, LAPL = dense_mtx(grcar()), dense_mtx(laplacian())

print("inspection tells the two kinds of matrix apart:")
b = client.post("/api/bounds", json={"matrix": LAPL}).json()
check("Hermitian matrix reports hermitian", b["hermitian"] is True)
check("...and gets an interval", "emin" in b and b["emin"] < b["emax"],
      f"[{b.get('emin'):.3g}, {b.get('emax'):.3g}]")
check("...and a disc as well", b["radius"] > 0)

g = client.post("/api/bounds", json={"matrix": GRCAR}).json()
check("non-Hermitian matrix reports non-hermitian", g["hermitian"] is False)
check("...and still gets a bounding disc", g["radius"] > 0,
      f"r={g['radius']:.3g} about {g['center_re']:.3g}")

print("\nthe region gate:")
r = client.post("/api/solve", json={"matrix": GRCAR, "emin": -1, "emax": 1})
check("interval search of a non-Hermitian matrix is refused", r.status_code == 400)
check("...with an error naming the disc", "disc" in r.json()["detail"].lower(),
      r.json()["detail"][:60])

r = client.post("/api/solve", json={"matrix": GRCAR, "emin": 0, "emax": 1,
                                    "center_re": 1, "radius": 2})
check("giving both regions is refused", r.status_code == 400)
r = client.post("/api/solve", json={"matrix": GRCAR})
check("giving neither region is refused", r.status_code == 400)
for bad in (0, -1):
    r = client.post("/api/solve", json={"matrix": GRCAR, "center_re": 1, "radius": bad})
    check(f"radius {bad} is refused with our own message",
          r.status_code == 400 and "radius" in r.json()["detail"].lower())

r = client.post("/api/estimate", json={"matrix": GRCAR, "center_re": 1, "radius": 4})
check("the estimator declines a disc rather than mis-parsing it",
      r.status_code == 400 and "interval" in r.json()["detail"].lower())

print("\ndisc search actually solves:")
r = client.post("/api/solve", json={"matrix": GRCAR, "center_re": 1.0,
                                    "center_im": 0.0, "radius": 4.0,
                                    "m0": 60, "contour_points": 16})
d = r.json()
check("Grcar solves", r.status_code == 200 and d["info"] == 0,
      f"info={d.get('info')}")
check("finds all 60", d.get("n_found") == 60, f"n_found={d.get('n_found')}")
check("residuals are small", max(d["residuals"]) < 1e-10,
      f"max={max(d['residuals']):.1e}")
check("eigenvalues come back as [re, im] pairs",
      d["complex_eigenvalues"] is True
      and all(isinstance(v, list) and len(v) == 2 for v in d["eigenvalues"]))
ev = np.array([complex(a, c) for a, c in d["eigenvalues"]])
check("they are genuinely off the real axis", np.abs(ev.imag).max() > 1.0,
      f"|imag| up to {np.abs(ev.imag).max():.2f}")
true = np.linalg.eigvals(grcar())
check("they match the true spectrum",
      max(min(abs(true - e)) for e in ev) < 1e-4,
      f"max distance {max(min(abs(true - e)) for e in ev):.1e}")
check("every one is inside the requested disc",
      np.all(np.abs(ev - 1.0) <= 4.0 + 1e-9))

print("\ninterval search is unchanged:")
r = client.post("/api/solve", json={"matrix": LAPL, "emin": 0.0, "emax": 0.5,
                                    "m0": 20})
d = r.json()
check("Laplacian solves", r.status_code == 200 and d["info"] == 0)
check("eigenvalues stay plain numbers",
      d["complex_eigenvalues"] is False
      and all(isinstance(v, float) for v in d["eigenvalues"]))
# 2 - 2cos(k pi / (n+1)), the known spectrum.
n = 40
exact = [2 - 2 * np.cos(k * np.pi / (n + 1)) for k in range(1, n + 1)]
inband = sorted(v for v in exact if 0.0 <= v <= 0.5)
check("it finds exactly the ones in the interval",
      d["n_found"] == len(inband), f"{d['n_found']} vs {len(inband)}")
check("and they are right",
      max(abs(a - b_) for a, b_ in zip(sorted(d["eigenvalues"]), inband)) < 1e-8)

print("\ndiagnostics follow the region, not the other way round:")
r = client.post("/api/solve", json={"matrix": GRCAR, "center_re": 40.0,
                                    "radius": 1.0, "m0": 20}).json()
check("an empty disc says disc", "disc" in r["headline"].lower(), r["headline"])
text = " ".join(s["text"] for s in r["suggestions"])
check("...and suggests a radius, not an interval",
      "radius" in text.lower() and "interval" not in text.lower())
check("...including the disc that bounds the spectrum",
      any(s["param"] == "disc" for s in r["suggestions"]))

r = client.post("/api/solve", json={"matrix": LAPL, "emin": 90.0, "emax": 95.0,
                                    "m0": 20}).json()
check("an empty interval still says interval",
      "interval" in r["headline"].lower(), r["headline"])
text = " ".join(s["text"] for s in r["suggestions"])
check("...and does not mention a radius", "radius" not in text.lower())

print("\nthe non-Hermitian sample is real and solvable:")
s = client.get("/api/samples/grcar").json()
check("sample declares disc mode", s.get("mode") == "disc")
check("sample ships a disc that contains its spectrum", s["radius"] > 0)
r = client.post("/api/solve", json={"matrix": s["text"],
                                    "center_re": s["center_re"],
                                    "center_im": s["center_im"],
                                    "radius": s["radius"], "m0": 150,
                                    "contour_points": 16}).json()
check("the sample solves as shipped", r.get("info") == 0 and r.get("n_found") == 120,
      f"info={r.get('info')} n={r.get('n_found')}")

print(f"\n{passed}/{passed + failed} passed")
sys.exit(1 if failed else 0)
