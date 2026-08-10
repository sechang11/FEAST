"""Check the plot-navigation and layout changes, and capture how a large
window apportions space."""
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app import GenerateDialog, MainWindow  # noqa: E402

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "qa_views")
app = None
w = None
fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'  ' + detail if detail else ''}")
    if not ok:
        fails.append(name)


def shot(name):
    OUT.mkdir(parents=True, exist_ok=True)
    w.grab().save(str(OUT / f"{name}.png"))
    print(f"  {OUT / name}.png")


def step1():
    # Where does extra space go when the window is large?
    w.resize(1920, 1080)
    app.processEvents()
    sizes = w.rsplit.sizes()
    print(f"  large window split (plot/table/log): {sizes}")
    check("plot gets the most space in a large window", sizes[0] >= sizes[1],
          f"plot={sizes[0]} table={sizes[1]}")

    # Generated matrix, via the dialog's own code path.
    dlg = GenerateDialog(w)
    dlg.kind.setCurrentText("sparse symmetric")
    dlg.n.setValue(3000)
    dlg.density.setValue(0.0005)
    dlg.seed.setValue(7)
    dlg.generate()
    check("dialog produced a matrix", dlg.result_matrices is not None)
    A, B, label = dlg.result_matrices
    check("generated matrix is sparse and the right size",
          A.shape == (3000, 3000), f"{A.shape}, {label}")
    sym, _ = __import__("feastpy").matrixio.check_symmetry(A)
    check("generated matrix is symmetric", sym)

    w.matrix, w.b_matrix = A, None
    w.matrix_label.setText(label)
    w._update_spectrum_view()
    w.use_full_range()
    check("bounds computed for generated matrix", w.bounds is not None, str(w.bounds))
    # Size M0 from an estimate rather than guessing: a random matrix can put
    # far more eigenvalues in a slice than a fixed M0 would hold, and info=2
    # (out of loops) is then the honest answer rather than a bug.
    w.emax.setValue(w.emin.value() + (w.bounds[1] - w.bounds[0]) * 0.02)
    import feastpy
    est = feastpy.estimate_count(w.matrix, w.emin.value(), w.emax.value())
    print(f"  estimated {est} eigenvalues in the slice")
    w.m0.setValue(max(20, int(est * 1.5) + 5))
    w.solve()
    QTimer.singleShot(400, wait_solve)


def wait_solve():
    if w.worker is not None and w.worker.isRunning():
        QTimer.singleShot(400, wait_solve)
        return
    r = w.result
    check("generated matrix solves", r is not None and r.info == 0,
          f"info={r.info if r else None} ({r.message if r else ''}) found={r.n_found if r else 0}")
    shot("01_large_window_generated")

    # Pan away, then prove Fit brings it back.
    vb = w.plot.getViewBox()
    before = vb.viewRange()[0]
    vb.setXRange(before[1] + 1000, before[1] + 1001, padding=0)
    app.processEvents()
    lost = vb.viewRange()[0]
    w.fit_view()
    app.processEvents()
    after = vb.viewRange()[0]
    check("fit_view recovers the data after panning away",
          abs(after[0] - lost[0]) > 1e-9 and after[0] < after[1],
          f"lost={lost[0]:.4g}..{lost[1]:.4g} -> {after[0]:.4g}..{after[1]:.4g}")

    # Pan limits should stop you wandering into empty space at all.
    lo, hi = w.bounds
    span = hi - lo
    vb.setXRange(hi + 10 * span, hi + 11 * span, padding=0)
    app.processEvents()
    xr = vb.viewRange()[0]
    check("pan limits keep the view near the data", xr[0] <= hi + span + 1e-6,
          f"clamped to {xr[0]:.4g}..{xr[1]:.4g} (limit {hi + span:.4g})")

    shot("02_after_fit")
    print(f"\n{'FAILURES: ' + ', '.join(fails) if fails else 'all checks passed'}")
    app.exit(1 if fails else 0)


def main():
    global app, w
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    QTimer.singleShot(700, step1)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
