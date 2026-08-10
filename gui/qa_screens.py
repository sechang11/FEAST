"""Capture the app in a range of states for a human to look at.

verify_gui.py proves behaviour; this exists to catch the things assertions do
not see -- crowding, truncation, empty states, what the app looks like before
you have done anything.

    python qa_screens.py <outdir>
"""
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app import CodeDialog, MainWindow  # noqa: E402

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "qa")
app = None
w = None
shots = []


def shot(name, widget=None):
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / f"{name}.png"
    (widget or w).grab().save(str(p))
    shots.append(p)
    print(f"  {p}")


def wait_idle(then, tries=[0]):
    """Run `then` once no solve is in flight."""
    def tick():
        if w.worker is not None and w.worker.isRunning():
            QTimer.singleShot(300, tick)
        else:
            then()
    QTimer.singleShot(300, tick)


def demo_named(fragment):
    names = [w.demo_combo.itemText(i) for i in range(w.demo_combo.count())]
    return next(n for n in names if fragment in n)


def step_1_first_launch():
    print("states:")
    shot("01_first_launch")                      # before anything is solved
    w.resize(900, 620)
    app.processEvents()
    shot("02_small_window")                      # does the layout hold up?
    w.resize(1180, 760)
    app.processEvents()
    step_2_dense()


def step_2_dense():
    w.demo_combo.setCurrentText(demo_named("Random symmetric"))
    app.processEvents()
    w.solve()
    wait_idle(step_3_dense_done)


def step_3_dense_done():
    shot("03_dense_random_symmetric")
    w.tabs.setCurrentIndex(1)
    app.processEvents()
    shot("04_convergence_dense")
    w.tabs.setCurrentIndex(0)
    w.demo_combo.setCurrentText(demo_named("2-D"))
    app.processEvents()
    shot("05_loaded_not_solved")                 # bounds known, no results yet
    w.use_full_range()
    app.processEvents()
    w.m0.setValue(60)
    w.solve()
    wait_idle(step_4_2d_done)


def step_4_2d_done():
    shot("06_2d_laplacian_full_spectrum")
    dlg = CodeDialog(w._code_spec(), w)
    dlg.show()
    app.processEvents()
    shot("07_code_python", dlg)
    dlg.lang.setCurrentIndex(1)
    app.processEvents()
    shot("08_code_c", dlg)
    dlg.close()
    # An interval with nothing in it: the empty-result state.
    w.emin.setValue(-5.0)
    w.emax.setValue(-4.0)
    app.processEvents()
    from PySide6.QtWidgets import QMessageBox
    QMessageBox.exec = lambda self, *a, **k: 0     # do not block on the dialog
    w.solve()
    wait_idle(step_5_empty)


def step_5_empty():
    shot("09_empty_interval_result")
    print(f"\n{len(shots)} screenshots in {OUT}")
    app.quit()


def main():
    global app, w
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    QTimer.singleShot(700, step_1_first_launch)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
