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
            finish()
            return

        fixes = [s for s in (diag.suggestions if diag else []) if s.actionable]
        if first:
            check("an applicable fix is offered", bool(fixes),
                  fixes[0].text if fixes else "none")
        if not fixes or state["attempts"] >= 3:
            check("the suggested fixes resolve the problem", False,
                  f"gave up at info={r.info} after {state['attempts']} fix(es)")
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


if __name__ == "__main__":
    sys.exit(main())
