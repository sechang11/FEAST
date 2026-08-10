"""Drives the GUI end to end and saves a screenshot, so a build can be checked
without a human clicking anything.

Exercises the whole intended flow: load -> spectral bounds -> estimate count
(which sets M0) -> drag the interval band -> solve.
"""
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app import MainWindow  # noqa: E402

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "gui_verify.png")

app = QApplication(sys.argv)
w = MainWindow()
w.show()

state = {"phase": "start", "ticks": 0}
failures = []


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

    if w.result is not None:
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
        print(f"\n{'FAILURES: ' + ', '.join(failures) if failures else 'all checks passed'}")
        app.exit(1 if failures else 0)
    elif state["ticks"] > 160:
        print("TIMEOUT: solve never completed")
        w.grab().save(str(OUT))
        app.exit(1)


QTimer.singleShot(600, start)
t = QTimer(); t.timeout.connect(poll); t.start(500)
sys.exit(app.exec())
