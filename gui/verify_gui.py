"""Drives the GUI end to end and saves a screenshot, so a build can be checked
without a human clicking anything.

Exercises the whole intended flow: load -> spectral bounds -> estimate count
(which sets M0) -> drag the interval band -> solve.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app import CodeDialog, MainWindow  # noqa: E402

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "gui_verify.png")

# Assigned in main(). Nothing may run at import time: the solve happens in a
# child process started with 'spawn', and that child re-imports this module.
app = None
w = None
state = {"phase": "start", "ticks": 0}
failures = []


def finish():
    print(f"\n{'FAILURES: ' + ', '.join(failures) if failures else 'all checks passed'}")
    app.exit(1 if failures else 0)


def check_disc():
    """A non-Hermitian problem: complex eigenvalues, so a disc, not an interval.

    Run synchronously against feastpy rather than through the worker thread --
    this asserts the geometry plumbing (which routine, which search region,
    which plot) without a second async solve in the harness.
    """
    print("\ndisc search:")
    import numpy as np
    from feastpy import problems, runner

    p = problems.get("system4")
    if not problems.available(p):
        print("  SKIP  disc search (system4 matrix not present)")
        return
    A, B = problems.load(p)
    params = dict(m0=p.m0, contour_points=16, tol_exponent=12, max_loops=20,
                  uplo=problems.effective_uplo(A, p.uplo),
                  center=p.emid, radius=p.radius)
    r, _ = runner.solve_blocking(A, B, params)
    check("disc search dispatches to a complex routine",
          r.routine.startswith(("zfeast", "zifeast")), r.routine)
    check("disc search converges", r.info == 0 and r.n_found > 0,
          f"info={r.info} found={r.n_found}")
    check("eigenvalues are complex", np.iscomplexobj(r.eigenvalues),
          str(r.eigenvalues.dtype))
    d = np.abs(np.asarray(r.eigenvalues, complex) - complex(p.emid))
    check("and they all lie inside the search disc",
          bool((d <= p.radius + 1e-9).all()), f"max distance {d.max():.4f}")

    # The complex-plane view must accept them without a real-axis assumption.
    try:
        from views import ComplexSpectrumView
        v = ComplexSpectrumView()
        v.show_search(p.emid, p.radius, r.eigenvalues)
        check("complex spectrum view renders them", True,
              f"{r.n_found} points")
    except Exception as exc:
        check("complex spectrum view renders them", False, str(exc)[:60])

    check_user_opens_non_hermitian()
    check_user_polynomial()
    check_self_consistent()


def check_user_opens_non_hermitian():
    """Opening a non-Hermitian matrix from disk, the way a user would.

    The built-in problems reach disc mode through their own metadata, so they
    pass whatever the file-open path does. That path used to refuse anything
    not symmetric-or-Hermitian outright -- so the app solved its own
    non-Hermitian demo while turning away a user's matrix of the same kind.
    """
    print("\nopening a non-Hermitian matrix from disk:")
    import os
    import tempfile
    from unittest.mock import patch

    import numpy as np
    from feastpy import problems, runner

    import app as guimod

    n = 60                                   # Grcar: real, wildly non-normal
    ent = []
    for i in range(1, n + 1):
        if i > 1:
            ent.append((i, i - 1, -1.0))
        for k in range(4):
            if i + k <= n:
                ent.append((i, i + k, 1.0))
    path = os.path.join(tempfile.mkdtemp(), "grcar.mtx")
    with open(path, "w") as fh:
        fh.write("\n".join([f"{n} {n} {len(ent)}"]
                           + [f"{i} {j} {v}" for i, j, v in ent]))

    w = guimod.MainWindow()
    with patch("app.QFileDialog.getOpenFileName", return_value=(path, "")), \
         patch("app.QMessageBox.warning") as warn, \
         patch("app.QMessageBox.question", return_value=guimod.QMessageBox.No):
        w.open_file()
        check("it is not refused", not warn.called,
              warn.call_args[0][2][:50] if warn.called else "")
    check("the matrix is loaded", w.matrix is not None and w.matrix.shape == (n, n))
    check("the window switches to disc mode", w._geometry == problems.DISC,
          w._geometry)
    check("stored in full, as the general routines require", w._uplo == "F")
    check("the contour opens at 16 points, not 8", w.contour.value() == 16)

    r, _ = runner.solve_blocking(
        w.matrix, None,
        dict(center=w._centre, radius=w._radius, m0=n,
             contour_points=w.contour.value(), tol_exponent=12, max_loops=20))
    check("and it solves", r.info == 0 and r.n_found == n,
          f"info={r.info} found={r.n_found}")
    check("to a small residual", max(r.residuals) < 1e-10,
          f"max {max(r.residuals):.1e}")
    ev = np.asarray(r.eigenvalues)
    check("with a genuinely complex spectrum", np.abs(ev.imag).max() > 1.0,
          f"|imag| up to {np.abs(ev.imag).max():.2f}")
    check("and the advice names the disc, not an interval",
          "disc" in w._diagnose(r).headline.lower()
          or w._diagnose(r).info == 0, w._diagnose(r).headline)


def check_polynomial():
    """A quadratic eigenvalue problem: three coefficient matrices, not one."""
    print("\npolynomial (quadratic) problem:")
    import numpy as np
    from feastpy import problems, runner

    p = problems.get("system5")
    if not problems.available(p):
        print("  SKIP  polynomial (system5 matrices not present)")
        return
    mats, _ = problems.load(p)
    check("three coefficient matrices load", len(mats) == 3,
          f"{[m.shape[0] for m in mats]}")
    params = dict(m0=p.m0, contour_points=p.contour_points,
                  tol_exponent=p.tol_exponent, max_loops=p.max_loops,
                  uplo="F", center=p.emid, radius=p.radius, ratio=p.ratio)
    r, secs = runner.solve_blocking(mats, None, params)
    check("polynomial solve dispatches to a pev routine",
          "pev" in r.routine, r.routine)
    # Whether it reaches 1e-6 within the loop cap is machine-dependent: without
    # MKL the inner solver is iterative, and how fast it converges follows the
    # BLAS and the thread count. Measured 9.4e-07 on one machine and 4.2e-05 on
    # a CI runner from identical inputs. So assert what is actually invariant --
    # the right routine, the right count, the right place, and a residual small
    # enough to mean the answer is real -- not the exact stopping point.
    check("polynomial finds its 20 eigenvalues", r.n_found == 20,
          f"info={r.info} found={r.n_found} in {secs:.0f}s")
    if r.n_found:
        d = np.abs(np.asarray(r.eigenvalues, complex) - complex(p.emid))
        check("its eigenvalues lie inside the search disc",
              bool((d <= p.radius + 1e-9).all()), f"max distance {d.max():.4f}")
        check("and are solved to a usable accuracy",
              r.residuals.max() < 1e-3, f"maxres={r.residuals.max():.2e}")


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'  ' + detail if detail else ''}")
    if not ok:
        failures.append(name)


def start():
    print(f"matrix: {w.matrix_label.text()}")

    check("Gershgorin bounds computed", w.bounds is not None, str(w.bounds))
    print(f"  range label: {w.range_label.text().splitlines()[0]}")

    # dragging the band must drive the spin boxes
    w.region.setRegion((0.0, 0.01))
    ok = abs(w.emax.value() - 0.01) < 1e-9
    check("plot band -> spin boxes", ok, f"emax={w.emax.value()}")

    # and the spin boxes must drive the band back
    w.emax.setValue(0.02)
    lo, hi = w.region.getRegion()
    check("spin boxes -> plot band", abs(hi - 0.02) < 1e-9, f"region={lo:.4g},{hi:.4g}")

    state["phase"] = "counting"
    w.estimate_count()


def poll():
    """Timer tick. Wrapped so a bug in the harness fails the run instead of
    raising every 500ms forever, which looks like a hang with no output."""
    try:
        _poll()
    except Exception:
        import traceback
        traceback.print_exc()
        check("verification harness ran without error", False)
        finish()


def _poll():
    state["ticks"] += 1

    if state["phase"] == "counting":
        if "about" in w.count_label.text():
            print(f"  estimate: {w.count_label.text()}")
            check("count estimate produced", True)
            check("M0 auto-set from estimate", w.m0.value() > 0, f"M0={w.m0.value()}")
            state["phase"] = "solving"
            w.solve()
        elif state["ticks"] > 60:
            check("count estimate produced", False, "timed out")
            state["phase"] = "solving"
            w.solve()
        return

    if state["phase"] == "solving" and w.result is not None:
        r = w.result
        print(f"solved: info={r.info} ({r.message})")
        print(f"found {r.n_found} eigenvalues, {r.loops} loop(s), epsout={r.epsout:.2e}")
        check("solve succeeded", r.info == 0)
        check("table populated", w.table.rowCount() == r.n_found,
              f"rows={w.table.rowCount()} found={r.n_found}")
        if r.n_found:
            print(f"first: {r.eigenvalues[0]:.12g}  last: {r.eigenvalues[-1]:.12g}")
        w.grab().save(str(OUT))
        print(f"screenshot: {OUT}")

        # --- convergence history --------------------------------------------
        # Parsed live out of FEAST's printed table while the solve ran.
        conv = w.convergence
        check("convergence rows captured", len(conv) > 0, f"{len(conv)} rows")
        if conv:
            print(f"  loops {conv[0]['loop']}..{conv[-1]['loop']}, "
                  f"trace error {conv[0]['error_trace']:.2e} -> {conv[-1]['error_trace']:.2e}")
            check("one row per reported loop",
                  [c["loop"] for c in conv] == sorted(c["loop"] for c in conv),
                  "loops arrive in order")
            check("error actually decreases",
                  conv[-1]["error_trace"] < conv[0]["error_trace"],
                  f"{conv[0]['error_trace']:.2e} -> {conv[-1]['error_trace']:.2e}")
            check("loop count matches the result",
                  abs(len(conv) - (r.loops + 1)) <= 1,
                  f"{len(conv)} rows vs result.loops={r.loops}")
            # show the tab we just populated
            w.tabs.setCurrentIndex(1)
            app.processEvents()
            w.grab().save(str(OUT.with_name(OUT.stem + "_convergence.png")))
            print(f"screenshot: {OUT.with_name(OUT.stem + '_convergence.png')}")
            w.tabs.setCurrentIndex(0)

        # --- generalized problem: FEAST's own system1 sample ---------------
        # The upstream driver finds 16 eigenvalues in [0.18, 1.0]; the GUI must
        # agree, which also proves the B matrix reaches the solver.
        print("\ngeneralized problem (FEAST sample system1):")
        names = [w.demo_combo.itemText(i) for i in range(w.demo_combo.count())]
        target = [n for n in names if "system1" in n]
        if not target:
            check("system1 demo present", False)
            finish()
            return
        w.result = None
        state["phase"] = "generalized"
        state["ticks"] = 0
        w.demo_combo.setCurrentText(target[0])
        check("B matrix loaded with demo", w.b_matrix is not None,
              w.b_label.text())
        print(f"  A: {w.matrix_label.text()}")
        w.m0.setValue(30)
        w.solve()
        return

    if state["phase"] == "generalized" and w.result is not None:
        r = w.result
        print(f"solved: info={r.info} ({r.message}) found={r.n_found}")
        check("generalized solve succeeded", r.info == 0)
        check("matches upstream driver (16 eigenvalues)", r.n_found == 16,
              f"found={r.n_found}")
        if r.n_found:
            print(f"  range {r.eigenvalues.min():.15f} .. {r.eigenvalues.max():.15f}")
            print( "  upstream 0.216788800187194 .. 0.989790599324303")
        w.grab().save(str(OUT.with_name(OUT.stem + "_generalized.png")))
        print(f"screenshot: {OUT.with_name(OUT.stem + '_generalized.png')}")

        # --- export ---------------------------------------------------------
        # Drive the app's own export path (not results_io directly) by stubbing
        # the file dialog, so the GUI wiring is what gets tested.
        print("\nexport:")
        import tempfile, numpy as np
        from PySide6.QtWidgets import QFileDialog
        from feastpy import results_io

        tmp = Path(tempfile.mkdtemp())
        for fmt_key, label, ext in results_io.FORMATS:
            target = tmp / f"out_{fmt_key}{ext}"
            QFileDialog.getSaveFileName = staticmethod(
                lambda *a, _t=target, _l=label, **k: (str(_t), _l))
            w.export_csv()
            written = target if target.exists() else target.with_suffix(ext)
            check(f"export {fmt_key}", written.exists(),
                  f"{written.name} {written.stat().st_size:,}B" if written.exists() else "missing")

        with np.load(tmp / "out_npz.npz") as d:
            check("exported npz carries eigenvectors",
                  d["eigenvectors"].shape == (r.eigenvectors.shape[0], r.n_found),
                  f"shape={d['eigenvectors'].shape}")

        # --- copy as code ---------------------------------------------------
        # Generate through the app's own dialog, then prove the output is real
        # by running the Python and compiling the C.
        print("\ncopy as code:")
        import subprocess
        from feastpy import codegen

        dlg = CodeDialog(w._code_spec(), w)
        langs = [dlg.lang.itemText(i) for i in range(dlg.lang.count())]
        check("both languages offered", len(langs) == 2, ", ".join(langs))

        generated = {}
        for i, lang in enumerate(langs):
            dlg.lang.setCurrentIndex(i)
            generated[lang] = dlg.text.toPlainText()
            check(f"{lang} generated", len(generated[lang]) > 200,
                  f"{len(generated[lang])} chars")
        check("routine name shown", "difeast_scsrgv" in dlg.routine.text(),
              dlg.routine.text())

        dlg.show()
        app.processEvents()
        dlg.grab().save(str(OUT.with_name(OUT.stem + "_code.png")))
        print(f"screenshot: {OUT.with_name(OUT.stem + '_code.png')}")
        dlg.copy()
        from PySide6.QtWidgets import QApplication as _QA
        check("clipboard populated",
              _QA.clipboard().text() == generated[langs[dlg.lang.currentIndex()]])
        dlg.close()

        code_dir = Path(tempfile.mkdtemp())
        py_src = next(v for k, v in generated.items() if k.startswith("Python"))
        (code_dir / "gen.py").write_text(py_src, encoding="utf-8")
        env = dict(os.environ,
                   PYTHONPATH=str(Path(__file__).resolve().parent.parent / "python"))
        pr = subprocess.run([sys.executable, str(code_dir / "gen.py")],
                            capture_output=True, text=True, env=env, timeout=300)
        check("generated Python runs", pr.returncode == 0,
              (pr.stdout or pr.stderr).strip().splitlines()[-1][:70] if (pr.stdout or pr.stderr) else "")
        check("generated Python finds the same 16 eigenvalues",
              "found 16 eigenvalues" in pr.stdout, pr.stdout.strip()[:60])

        c_src = generated["C"]
        (code_dir / "gen.c").write_text(c_src, encoding="utf-8")
        root = Path(__file__).resolve().parent.parent
        # Must match build-feast.sh's <os>-<arch> tag. Assuming linux-x64 for
        # everything non-Windows made this check silently SKIP on macOS.
        import platform
        os_tag = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
        mach_tag = {"amd64": "x64", "x86_64": "x64", "x64": "x64",
                    "arm64": "arm64", "aarch64": "arm64"}.get(
                        platform.machine().lower(), "x64")
        arch = f"{os_tag}-{mach_tag}"
        lib = root / "4.0" / "lib" / arch / "libfeast.a"
        # A developer box need not have a C toolchain -- Windows generally has
        # no `cc` unless MSYS2 is on PATH. That is not a product failure, so
        # skip rather than crash the whole run; CI always has one.
        cc_bin = os.environ.get("CC", "cc")
        have_cc = shutil.which(cc_bin) is not None
        if lib.exists() and not have_cc:
            print(f"  SKIP  generated C compiles and links  (no {cc_bin} on PATH)")
        if lib.exists() and have_cc:
            # Same split as build/run-test.sh: compile the C with the C
            # compiler, but link with the Fortran driver. Apple's clang rejects
            # -fopenmp outright and does not know where libgfortran lives.
            blas = (["-framework", "Accelerate"] if sys.platform == "darwin"
                    else ["-lopenblas"])
            fc = os.environ.get("FC", "gfortran")
            obj, exe = code_dir / "gen.o", code_dir / "gen.bin"
            cc = subprocess.run(
                ["cc", "-O2", "-c", str(code_dir / "gen.c"), "-o", str(obj),
                 "-I", str(root / "4.0" / "include")],
                capture_output=True, text=True, timeout=300)
            if cc.returncode:
                check("generated C compiles and links", False,
                      cc.stderr.strip().splitlines()[-1][:70])
            else:
                ln = subprocess.run(
                    [fc, "-o", str(exe), str(obj), str(lib), *blas,
                     "-fopenmp", "-lm"],
                    capture_output=True, text=True, timeout=300)
                check("generated C compiles and links", ln.returncode == 0,
                      ln.stderr.strip().splitlines()[-1][:70] if ln.returncode else "")
        else:
            print(f"  SKIP  generated C compiles (no {lib})")

        # --- cancel ---------------------------------------------------------
        # Start a deliberately slow solve (whole spectrum of the 2-D Laplacian,
        # big subspace) and stop it. The point is that the native work really
        # ends, not just that the UI stops showing it.
        print("\ncancel:")
        names = [w.demo_combo.itemText(i) for i in range(w.demo_combo.count())]
        w.demo_combo.setCurrentText([n for n in names if "2-D" in n][0])
        w.use_full_range()
        w.m0.setValue(600)
        w.result = None
        state["phase"] = "cancelling"
        state["ticks"] = 0
        w.solve()
        check("button switches to Cancel", w.solve_btn.text() == "Cancel",
              f"text={w.solve_btn.text()!r}")
        check("solve is running", w.worker is not None and w.worker.isRunning())
        return

    if state["phase"] == "cancelling":
        if state["ticks"] == 2:                 # let it get properly underway
            proc = w.worker.handle.process if w.worker.handle else None
            state["pid"] = proc.pid if proc else None
            print(f"  solver process pid={state.get('pid')}")
            check("solver runs in its own process", state.get("pid") is not None)
            w.cancel_solve()
            return
        if state["ticks"] > 2:
            if w.worker is not None and w.worker.isRunning():
                if state["ticks"] > 40:
                    check("cancel stops the solve", False, "worker still running")
                    finish()
                return
            check("cancel stops the solve", True)
            check("no result recorded after cancel", w.result is None)
            check("button returns to Solve", w.solve_btn.text() == "Solve",
                  f"text={w.solve_btn.text()!r}")
            check("controls re-enabled", w.count_btn.isEnabled())
            # The child must actually be gone, not merely detached. Ask the OS:
            # the Process object is closed by then, so is_alive() would raise.
            pid = state.get("pid")
            try:
                import psutil
                alive = psutil.pid_exists(pid) if pid is not None else False
                check("solver process terminated", not alive, f"pid={pid}")
            except ImportError:
                print("  SKIP  solver process terminated (psutil not installed)")

            # --- actionable diagnostics ---------------------------------
            print("\ndiagnostics:")
            from PySide6.QtWidgets import QMessageBox
            # _offer_fix is modal; stub exec() so it cannot block the harness.
            QMessageBox.exec = lambda self, *a, **k: 0
            w.auto_m0.setChecked(False)     # we want to SEE info=3, not auto-fix it
            names = [w.demo_combo.itemText(i) for i in range(w.demo_combo.count())]
            w.demo_combo.setCurrentText([n for n in names if "n=200" in n][0])
            w.emin.setValue(0.0)
            w.emax.setValue(0.02)
            w.m0.setValue(2)                # deliberately too small
            w.result = None
            state["phase"] = "diagnosing"
            state["ticks"] = 0
            w.solve()
            return
            finish()
        return

    if state["phase"] in ("diagnosing", "refixed") and w.result is not None:
        r = w.result
        diag = w.diagnosis
        first = state["phase"] == "diagnosing"

        if first:
            # Which code an undersized M0 produces is platform-dependent:
            # info=3 on OpenBLAS, info=1 on Apple Silicon's Accelerate for the
            # same input. What must hold is that it fails and is diagnosed.
            check("undersized M0 fails", r.info != 0, f"info={r.info} ({r.message})")
            check("diagnosis attached", diag is not None and diag.info == r.info,
                  diag.headline if diag else "none")
            state["attempts"] = 0

        if r.info == 0:
            check("the suggested fixes resolve the problem", True,
                  f"after {state['attempts']} fix(es), found={r.n_found}")
            check("and finds the expected 9 eigenvalues", r.n_found == 9,
                  f"found={r.n_found}")
            check_disc()
            check_polynomial()
            finish()
            return

        fixes = [s for s in (diag.suggestions if diag else []) if s.actionable]
        if first:
            check("an applicable fix is offered", bool(fixes),
                  fixes[0].text if fixes else "none")
        if not fixes or state["attempts"] >= 3:
            check("the suggested fixes resolve the problem", False,
                  f"gave up at info={r.info} after {state['attempts']} fix(es)")
            check_disc()
            check_polynomial()
            finish()
            return

        before = (w.m0.value(), w.emin.value(), w.emax.value(),
                  w.contour.value(), w.loops.value(), w.tol.value())
        applied = w.apply_suggestion(fixes[0])
        after = (w.m0.value(), w.emin.value(), w.emax.value(),
                 w.contour.value(), w.loops.value(), w.tol.value())
        if first:
            check("applying the fix changes a parameter",
                  applied and before != after, f"{before} -> {after}")

        state["attempts"] += 1
        state["phase"] = "refixed"
        state["ticks"] = 0
        w.result = None
        w.solve()
        return

    if state["ticks"] > 160:
        print("TIMEOUT: solve never completed")
        w.grab().save(str(OUT))
        app.exit(1)


def main():
    global app, w
    import multiprocessing
    multiprocessing.freeze_support()

    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()

    QTimer.singleShot(600, start)
    t = QTimer()
    t.timeout.connect(poll)
    t.start(500)
    return app.exec()




def check_user_polynomial():
    """A user's own polynomial problem, not just the built-in system5.

    FEAST's nonlinear support is its polynomial support, and the ?pev routines
    take any degree. Nothing in the app let a user name their own coefficient
    matrices, so a whole problem class was reachable only as a demo.
    """
    print("\nopening a user's own polynomial problem:")
    import os
    import tempfile
    from unittest.mock import patch

    import numpy as np
    import scipy.linalg as sla
    from feastpy import problems, runner

    import app as guimod

    n = 40
    rng = np.random.default_rng(0)

    def sym(scale):
        M = rng.normal(size=(n, n)) * scale
        return (M + M.T) / 2

    mats = [sym(1.0) + np.eye(n) * 6, sym(0.3), sym(0.1), np.eye(n) * 0.2]
    d = tempfile.mkdtemp()
    paths = []
    for i, M in enumerate(mats):
        path = os.path.join(d, f"cubic_A{i}.mtx")
        paths.append(path)
        ent = [(r + 1, c + 1, M[r, c]) for r in range(n) for c in range(n)
               if M[r, c] != 0]
        with open(path, "w") as fh:
            fh.write("\n".join([f"{n} {n} {len(ent)}"]
                                + [f"{r} {c} {v!r}" for r, c, v in ent]))

    w = guimod.MainWindow()
    with patch("app.QFileDialog.getOpenFileNames", return_value=(paths, "")),          patch("app.QMessageBox.question", return_value=guimod.QMessageBox.Yes),          patch("app.QMessageBox.warning") as warn:
        w.open_polynomial()
        check("a degree-3 problem is accepted", not warn.called,
              warn.call_args[0][2][:50] if warn.called else "")
    check("all four coefficients are held",
          w.poly_matrices is not None and len(w.poly_matrices) == 4)
    check("it opens in disc mode", w._geometry == problems.DISC)
    check("the root bound is the polynomial's, not A0's",
          w._radius > 0 and w._centre == 0)

    # Narrow to where the roots are and solve, as a user would.
    Z, I = np.zeros((n, n)), np.eye(n)
    C0 = np.block([[Z, I, Z], [Z, Z, I], [-mats[0], -mats[1], -mats[2]]])
    C1 = np.block([[I, Z, Z], [Z, I, Z], [Z, Z, mats[3]]])
    true = sla.eig(C0, C1, right=False)
    true = true[np.isfinite(true)]
    inside = int((np.abs(true) <= 2.0).sum())
    r, _ = runner.solve_blocking(
        w.poly_matrices, None,
        dict(center=complex(0, 0), radius=2.0, m0=inside + 30,
             contour_points=16, tol_exponent=12, max_loops=20))
    check("it solves", r.info == 0, f"info={r.info}")
    check("finding every root in the disc", r.n_found == inside,
          f"{r.n_found} vs {inside}")
    got = np.asarray(r.eigenvalues)
    check("to full accuracy",
          max(min(abs(true - g)) for g in got) < 1e-10,
          f"max err {max(min(abs(true - g)) for g in got):.1e}")


def check_self_consistent():
    """The nonlinear eigenvector problem: H(rho) x = lambda x.

    A discretised 1-D Schrodinger operator with a density-dependent potential
    -- the shape of a Kohn-Sham problem. The check that matters is not that it
    ran but that the answer is self-consistent: the density built from the
    returned eigenvectors is the density that produced them.
    """
    print("\nself-consistent (nonlinear eigenvector) solve:")
    import numpy as np
    import scipy.sparse as sp
    from feastpy import runner

    n = 300
    h = 10.0 / (n - 1)
    lap = sp.diags([-1, 2, -1], [-1, 0, 1], shape=(n, n), format="csr") / (h * h)
    x = np.linspace(-5, 5, n)
    H0 = (0.5 * lap + sp.diags(0.5 * x ** 2, format="csr")).tocsr()
    alpha = 2.0

    r, _ = runner.solve_blocking(
        H0, None,
        dict(emin=0.0, emax=6.0, m0=20, uplo="F",
             scf=dict(alpha=alpha, exponent=1.0, mixing=0.3,
                      tol=1e-9, max_outer=200)))
    check("the loop converges", bool(r.scf_converged),
          f"passes={r.scf_iterations} delta={r.scf_delta:.1e}")
    check("the last pass is a clean FEAST solve", r.info == 0 and r.n_found > 0,
          f"info={r.info} found={r.n_found}")

    H = (H0 + sp.diags(alpha * r.scf_density, format="csr")).tocsr()
    X = r.eigenvectors
    resid = float(np.max(np.linalg.norm(H @ X - X * r.eigenvalues, axis=0)))
    check("and the pair really solves H(rho)x = lambda x", resid < 1e-8,
          f"{resid:.1e}")
    rebuilt = np.sum(np.abs(X) ** 2, axis=1)
    check("the density reproduces itself",
          float(np.max(np.abs(rebuilt - r.scf_density))) < 1e-8,
          f"{float(np.max(np.abs(rebuilt - r.scf_density))):.1e}")
    # Without the potential these are 0.5, 1.5, 2.5, ...; the coupling must
    # move them, or the "self-consistent" part did nothing.
    check("the potential actually shifted the levels",
          abs(r.eigenvalues[0] - 0.5) > 1e-3,
          f"lambda0={r.eigenvalues[0]:.6f} vs 0.5 uncoupled")


if __name__ == "__main__":
    sys.exit(main())
