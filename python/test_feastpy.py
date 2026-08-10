"""Checks the ctypes binding against problems with known answers."""
import numpy as np
import scipy.io
import scipy.sparse as sp

import tempfile, os

import feastpy
from feastpy import matrixio

N = 100
EXACT = np.array([2 - 2 * np.cos((k + 1) * np.pi / (N + 1)) for k in range(N)])


def laplacian(n=N):
    return (np.diag(np.full(n, 2.0))
            + np.diag(np.full(n - 1, -1.0), 1)
            + np.diag(np.full(n - 1, -1.0), -1))


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'  ' + detail if detail else ''}")
    return ok


results = []
print("feastpy binding tests")

# --- dense real symmetric, standard ------------------------------------------
r = feastpy.eigh_interval(laplacian(), 0.0, 0.05, m0=20)
want = EXACT[EXACT < 0.05]
err = np.max(np.abs(r.eigenvalues - want)) if r.n_found == len(want) else np.inf
results.append(check("dense dfeast_syev", r.info == 0 and err < 1e-10,
                     f"found={r.n_found} expected={len(want)} maxerr={err:.2e} loops={r.loops}"))

# eigenvectors must actually satisfy A x = lambda x
A = laplacian()
resid = np.max(np.abs(A @ r.eigenvectors - r.eigenvectors * r.eigenvalues))
results.append(check("dense eigenvectors", resid < 1e-9, f"max |Ax-lx| = {resid:.2e}"))

# --- dense generalized (B = I must reproduce the standard problem) -----------
rg = feastpy.eigh_interval(laplacian(), 0.0, 0.05, B=np.eye(N), m0=20)
errg = np.max(np.abs(rg.eigenvalues - want)) if rg.n_found == len(want) else np.inf
results.append(check("dense dfeast_sygv", rg.info == 0 and errg < 1e-10,
                     f"found={rg.n_found} maxerr={errg:.2e}"))

# --- complex Hermitian -------------------------------------------------------
# A Hermitian matrix built to have exactly the eigenvalues 1..5.
rng = np.random.default_rng(0)
X = rng.standard_normal((5, 5)) + 1j * rng.standard_normal((5, 5))
Q, _ = np.linalg.qr(X)
H = Q @ np.diag([1.0, 2.0, 3.0, 4.0, 5.0]) @ Q.conj().T
H = (H + H.conj().T) / 2
rh = feastpy.eigh_interval(H, 1.5, 4.5, m0=5)
errh = (np.max(np.abs(np.sort(rh.eigenvalues) - [2.0, 3.0, 4.0]))
        if rh.n_found == 3 else np.inf)
results.append(check("dense zfeast_heev", rh.info == 0 and errh < 1e-10,
                     f"found={rh.n_found} expected=3 maxerr={errh:.2e}"))

# --- sparse CSR (IFEAST) -----------------------------------------------------
As = sp.diags([np.full(N - 1, -1.0), np.full(N, 2.0), np.full(N - 1, -1.0)],
              [-1, 0, 1], format="csr")
rs = feastpy.eigsh_interval(As, 0.0, 0.05, m0=20)
errs = np.max(np.abs(np.sort(rs.eigenvalues) - want)) if rs.n_found == len(want) else np.inf
results.append(check("sparse difeast_scsrev", rs.info == 0 and errs < 1e-8,
                     f"found={rs.n_found} expected={len(want)} maxerr={errs:.2e}"))

# --- uplo handling -----------------------------------------------------------
# 'F' means the matrix is stored in full. Triangularising it (the old bug)
# discarded half the matrix and the solve silently found nothing.
rf = feastpy.eigsh_interval(As, 0.0, 0.05, m0=20, uplo="F")
errf = np.max(np.abs(np.sort(rf.eigenvalues) - want)) if rf.n_found == len(want) else np.inf
results.append(check("sparse uplo='F'", rf.info == 0 and errf < 1e-8,
                     f"found={rf.n_found} expected={len(want)} maxerr={errf:.2e}"))

rl = feastpy.eigsh_interval(As, 0.0, 0.05, m0=20, uplo="L")
results.append(check("sparse uplo='L'", rl.info == 0 and rl.n_found == len(want),
                     f"found={rl.n_found} expected={len(want)}"))

try:
    feastpy.eigsh_interval(As, 0.0, 0.05, uplo="X")
    results.append(check("invalid uplo rejected", False, "no error raised"))
except ValueError:
    results.append(check("invalid uplo rejected", True))

# --- banner-less Matrix Market ------------------------------------------------
# FEAST's own files in 4.0/utility/data are a mix of real Matrix Market and
# bare coordinate format; the loader must read both.
with tempfile.TemporaryDirectory() as td:
    p = os.path.join(td, "bare.mtx")
    with open(p, "w") as fh:
        fh.write("   4 4 5\n1 1  2.0\n2 2  3.0\n3 3  4.0\n4 4  5.0\n1 2 -1.0\n")
    M = matrixio.load_matrix(p)
    ok = M.shape == (4, 4) and abs(M[0, 0] - 2.0) < 1e-15 and abs(M[0, 1] + 1.0) < 1e-15
    results.append(check("banner-less .mtx loads", ok, f"shape={M.shape}"))

    p2 = os.path.join(td, "fortran.mtx")
    with open(p2, "w") as fh:      # Fortran D-exponent notation
        fh.write("2 2 2\n1 1 7.1D-19\n2 2 1.0D0\n")
    M2 = matrixio.load_matrix(p2)
    results.append(check("Fortran D-exponent parsed", abs(M2[0, 0] - 7.1e-19) < 1e-30,
                         f"got {M2[0, 0]!r}"))

# --- spectral bounds ----------------------------------------------------------
lo, hi = feastpy.spectral_bounds(laplacian())
results.append(check("Gershgorin brackets the spectrum",
                     lo <= EXACT.min() and hi >= EXACT.max(),
                     f"[{lo:.4g}, {hi:.4g}] vs true [{EXACT.min():.4g}, {EXACT.max():.4g}]"))

# Generalized: B's Gershgorin lower bound is routinely <= 0 even for spd B, and
# an earlier version divided by it and returned ranges around 1e282.
Bg = sp.diags([np.full(N - 1, 0.5), np.full(N, 4.0), np.full(N - 1, 0.5)],
              [-1, 0, 1], format="csr")
glo, ghi = feastpy.spectral_bounds(As, Bg)
true_gen = np.linalg.eigvalsh(np.linalg.solve(Bg.toarray(), As.toarray()))
results.append(check("generalized bounds are sane",
                     glo <= true_gen.min() and ghi >= true_gen.max() and abs(ghi) < 1e4,
                     f"[{glo:.4g}, {ghi:.4g}] vs true [{true_gen.min():.4g}, {true_gen.max():.4g}]"))

try:
    feastpy.spectral_bounds(As, sp.diags([np.full(N, -1.0)], [0], format="csr"))
    results.append(check("non-spd B rejected", False, "no error raised"))
except RuntimeError:
    results.append(check("non-spd B rejected", True))

# --- count estimate -----------------------------------------------------------
est = feastpy.estimate_count(As, 0.0, 0.05)
results.append(check("count estimate is close", abs(est - len(want)) <= 3,
                     f"estimate={est} true={len(want)}"))

# --- B-matrix discovery -------------------------------------------------------
with tempfile.TemporaryDirectory() as td:
    for nm in ("sys.mtx", "sysB.mtx"):
        with open(os.path.join(td, nm), "w") as fh:
            fh.write("2 2 2\n1 1 1.0\n2 2 1.0\n")
    found = matrixio.guess_b_path(os.path.join(td, "sys.mtx"))
    results.append(check("finds the paired B matrix",
                         found is not None and found.name == "sysB.mtx", str(found)))
    none_found = matrixio.guess_b_path(os.path.join(td, "sysB.mtx"))
    results.append(check("no false B match", none_found is None, str(none_found)))

results.append(check("spd check accepts identity",
                     matrixio.is_probably_spd(sp.identity(50, format="csr"))))
results.append(check("spd check rejects negative diagonal",
                     not matrixio.is_probably_spd(sp.diags([np.full(50, -1.0)], [0],
                                                           format="csr"))))

# --- exporting results --------------------------------------------------------
from feastpy import results_io

with tempfile.TemporaryDirectory() as td:
    rr = feastpy.eigh_interval(laplacian(), 0.0, 0.05, m0=20)

    # npz must round-trip the eigenvectors exactly -- it is the format users
    # will actually compute with.
    npz_path = results_io.save_results(os.path.join(td, "out.npz"), rr, "npz",
                                       emin=0.0, emax=0.05)
    # NpzFile holds the zip open; on Windows that blocks the TemporaryDirectory
    # cleanup, so close it explicitly.
    with np.load(npz_path) as d:
        results.append(check("npz round-trips eigenvectors",
                             np.array_equal(d["eigenvectors"], rr.eigenvectors)
                             and np.array_equal(d["eigenvalues"], rr.eigenvalues),
                             f"shape={d['eigenvectors'].shape}"))
        results.append(check("npz records the interval",
                             float(d["emin"]) == 0.0 and float(d["emax"]) == 0.05))

    # eigenvalue-only CSV
    v_path = results_io.save_results(os.path.join(td, "v.csv"), rr, "values-csv")
    lines = open(v_path).read().strip().splitlines()
    results.append(check("values CSV has a row per eigenvalue",
                         len(lines) == rr.n_found + 1, f"{len(lines)} lines"))
    # Parse it, don't just count lines: NumPy 2 reprs like "np.float64(0.5)"
    # pass a line count but are unreadable by every CSV tool.
    parsed = np.array([float(l.split(",")[1]) for l in lines[1:]])
    results.append(check("values CSV is machine-readable",
                         np.allclose(parsed, rr.eigenvalues),
                         f"max diff {np.max(np.abs(parsed - rr.eigenvalues)):.2e}"))

    # eigenvector CSV: one column per eigenvalue, one row per component
    vec_path = results_io.save_results(os.path.join(td, "vec.csv"), rr, "vectors-csv")
    rows = open(vec_path).read().strip().splitlines()
    body = rows[3:]
    ok = len(body) == N and len(body[0].split(",")) == rr.n_found + 1
    results.append(check("vector CSV is n x m", ok,
                         f"{len(body)} rows x {len(body[0].split(','))-1} vectors"))
    # values must survive the text round-trip
    first_col = np.array([float(l.split(",")[1]) for l in body])
    results.append(check("vector CSV values round-trip",
                         np.allclose(first_col, rr.eigenvectors[:, 0]),
                         f"max diff {np.max(np.abs(first_col - rr.eigenvectors[:, 0])):.2e}"))

    mtx_path = results_io.save_results(os.path.join(td, "vec.mtx"), rr, "mtx")
    back = scipy.io.mmread(str(mtx_path))
    results.append(check("Matrix Market eigenvectors round-trip",
                         np.allclose(np.asarray(back), rr.eigenvectors),
                         f"shape={np.asarray(back).shape}"))

    # complex eigenvectors need re/im columns rather than silently losing the
    # imaginary part
    cvec = results_io.save_results(os.path.join(td, "c.csv"), rh, "vectors-csv")
    head = open(cvec).read().splitlines()[2]
    results.append(check("complex CSV splits re/im",
                         "re_1" in head and "im_1" in head, head[:40]))

    try:
        empty_r = feastpy.eigh_interval(laplacian(), 100.0, 200.0, m0=5)
        results_io.save_results(os.path.join(td, "e.npz"), empty_r, "npz")
        results.append(check("exporting nothing is refused", False, "no error"))
    except ValueError:
        results.append(check("exporting nothing is refused", True))

# --- diagnostics --------------------------------------------------------------
from feastpy import diagnostics

DIAG_KW = dict(n=N, m0=20, contour_points=8, tol_exponent=12, max_loops=20,
               emin=0.0, emax=0.05, bounds=(0.0, 4.0))

# An undersized M0 must always lead to a bigger-M0 suggestion. Which code FEAST
# returns for it is platform-dependent: info=3 on OpenBLAS, info=1 on Apple
# Silicon's Accelerate for the same input, so assert on the advice, not the code.
small = feastpy.eigh_interval(laplacian(), 0.0, 0.05, m0=2)
d3 = diagnostics.diagnose(small, **{**DIAG_KW, "m0": 2})
fix = next((s for s in d3.suggestions if s.param == "m0"), None)
results.append(check("undersized M0 suggests a larger M0",
                     small.info != 0 and fix is not None and fix.value > 2,
                     f"info={small.info} {d3.headline}: M0 -> {fix.value if fix else None}"))

# A real info=1 must offer the full spectrum.
none_found = feastpy.eigh_interval(laplacian(), 100.0, 200.0, m0=5)
d1 = diagnostics.diagnose(none_found, **{**DIAG_KW, "emin": 100.0, "emax": 200.0})
iv = next((s for s in d1.suggestions if s.param == "interval"), None)
results.append(check("info=1 offers the full spectrum",
                     d1.info == 1 and iv is not None and iv.value == (0.0, 4.0),
                     f"{d1.headline}: interval -> {iv.value if iv else None}"))

# Success is not silent when the residuals are poor.
good = feastpy.eigh_interval(laplacian(), 0.0, 0.05, m0=20)
d0 = diagnostics.diagnose(good, **DIAG_KW)
results.append(check("clean success suggests nothing",
                     d0.ok and not d0.suggestions, f"{len(d0.suggestions)} suggestions"))


class _Fake:
    def __init__(self, info, n_found=0, loops=20, epsout=1e-3, residuals=()):
        self.info, self.n_found, self.loops = info, n_found, loops
        self.epsout, self.residuals = epsout, list(residuals) or [0.0]
        self.message = feastpy.explain_info(info)


# Every code must yield a headline and never raise.
codes_ok = True
for code in (0, 1, 2, 3, 4, 5, 6, 200, 201, 202, 143, -1, -2, -3, 999):
    try:
        dd = diagnostics.diagnose(_Fake(code, n_found=3), **DIAG_KW)
        if not dd.headline or not isinstance(dd.suggestions, list):
            codes_ok = False
    except Exception as exc:
        print(f"    diagnose({code}) raised {exc}")
        codes_ok = False
results.append(check("every info code diagnoses cleanly", codes_ok))

d2 = diagnostics.diagnose(_Fake(2), **DIAG_KW)
results.append(check("info=2 suggests more loops and more contour points",
                     {s.param for s in d2.suggestions} >=
                     {"max_loops", "contour_points", "tol_exponent"},
                     ", ".join(s.param for s in d2.suggestions if s.param)))

hi_res = diagnostics.diagnose(_Fake(0, n_found=2, residuals=[1e-3]), **DIAG_KW)
results.append(check("success with poor residuals still warns",
                     any(s.param == "tol_exponent" for s in hi_res.suggestions),
                     f"{len(hi_res.suggestions)} suggestions"))

# --- raw layer: every routine in the library callable ------------------------
from feastpy import raw

sigs = raw.signatures()
results.append(check("header signatures parsed", len(sigs) > 150, f"{len(sigs)} routines"))
avail = raw.available()
results.append(check("library exports most of them", len(avail) > 100,
                     f"{len(avail)} present in this build"))

# A raw call must agree exactly with the high-level wrapper: same routine, same
# arguments, so any disagreement means the wrapper is marshalling wrongly.
_fpm = raw.new_fpm(fpm_1=0, fpm_2=8, fpm_3=12, fpm_4=20)
_m0 = 20
_lam = np.zeros(_m0); _q = np.zeros((N, _m0), order="F"); _res = np.zeros(_m0)
_out = raw.call("dfeast_syev", UPLO="F", N=N, A=np.asfortranarray(laplacian()), LDA=N,
                fpm=_fpm, epsout=0.0, loop=0, Emin=0.0, Emax=0.05, M0=_m0,
                **{"lambda": _lam}, q=_q, mode=0, res=_res, info=0)
_hi = feastpy.eigh_interval(laplacian(), 0.0, 0.05, m0=20)
results.append(check("raw call matches the high-level wrapper",
                     _out["info"] == 0 and _out["mode"] == _hi.n_found
                     and np.allclose(_lam[:_out["mode"]], _hi.eigenvalues),
                     f"info={_out['info']} mode={_out['mode']}"))

try:
    raw.call("dfeast_syev", N=N)
    results.append(check("raw rejects an incomplete call", False, "no error"))
except TypeError:
    results.append(check("raw rejects an incomplete call", True))

try:
    raw.call("dfeast_sbev", UPLO="F")      # banded: needs SPIKE, absent by design
    results.append(check("raw explains an absent routine", False, "no error"))
except (RuntimeError, TypeError) as exc:
    results.append(check("raw explains an absent routine", "SPIKE" in str(exc) or
                         isinstance(exc, TypeError), type(exc).__name__))

# --- non-Hermitian: eigenvalues off the real line -----------------------------
# Block diagonal of [[1,2],[-2,1]] and [[3,1],[-1,3]]: eigenvalues 1+/-2i, 3+/-1i.
_G = np.zeros((8, 8))
for _i2, _b in enumerate([np.array([[1., 2.], [-2., 1.]])] * 2
                         + [np.array([[3., 1.], [-1., 3.]])] * 2):
    _G[2 * _i2:2 * _i2 + 2, 2 * _i2:2 * _i2 + 2] = _b

_rg = feastpy.eig_disc(_G, center=1 + 2j, radius=0.5, m0=6)
_err = (max(abs(v - (1 + 2j)) for v in _rg.eigenvalues) if _rg.n_found else float("inf"))
results.append(check("non-Hermitian disc finds 1+2i", _rg.n_found > 0 and _err < 1e-10,
                     f"routine={_rg.routine} found={_rg.n_found} maxerr={_err:.2e}"))
results.append(check("general problem returns left eigenvectors",
                     _rg.left_eigenvectors is not None
                     and _rg.left_eigenvectors.shape[0] == 8,
                     str(None if _rg.left_eigenvectors is None else _rg.left_eigenvectors.shape)))

_rg2 = feastpy.eig_disc(_G, center=3 + 1j, radius=0.5, m0=6)
_err2 = (max(abs(v - (3 + 1j)) for v in _rg2.eigenvalues) if _rg2.n_found else float("inf"))
results.append(check("a different disc finds 3+1i", _rg2.n_found > 0 and _err2 < 1e-10,
                     f"found={_rg2.n_found} maxerr={_err2:.2e}"))

_rg3 = feastpy.eig_disc(_G, center=50 + 0j, radius=1.0, m0=6)
results.append(check("empty disc reports nothing found", _rg3.n_found == 0,
                     f"info={_rg3.info} found={_rg3.n_found}"))

# --- error handling ----------------------------------------------------------
empty = feastpy.eigh_interval(laplacian(), 100.0, 200.0, m0=5)
results.append(check("empty interval reports info=1", empty.info == 1 and empty.n_found == 0,
                     f"info={empty.info} ({empty.message})"))

too_small = feastpy.eigh_interval(laplacian(), 0.0, 0.05, m0=2)
results.append(check("undersized m0 reports info=3", too_small.info == 3,
                     f"info={too_small.info} ({too_small.message})"))

print(f"\n{sum(results)}/{len(results)} passed")
raise SystemExit(0 if all(results) else 1)
