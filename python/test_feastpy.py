"""Checks the ctypes binding against problems with known answers."""
import numpy as np
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

# --- error handling ----------------------------------------------------------
empty = feastpy.eigh_interval(laplacian(), 100.0, 200.0, m0=5)
results.append(check("empty interval reports info=1", empty.info == 1 and empty.n_found == 0,
                     f"info={empty.info} ({empty.message})"))

too_small = feastpy.eigh_interval(laplacian(), 0.0, 0.05, m0=2)
results.append(check("undersized m0 reports info=3", too_small.info == 3,
                     f"info={too_small.info} ({too_small.message})"))

print(f"\n{sum(results)}/{len(results)} passed")
raise SystemExit(0 if all(results) else 1)
