"""Drives the GUI end to end and saves a screenshot, so a build can be checked
without a human clicking anything."""
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

state = {"ticks": 0}


def start():
    print(f"matrix: {w.matrix_label.text()}")
    w.solve()


def poll():
    state["ticks"] += 1
    if w.result is not None:
        r = w.result
        print(f"solved: info={r.info} ({r.message})")
        print(f"found {r.n_found} eigenvalues, {r.loops} loop(s), epsout={r.epsout:.2e}")
        print(f"table rows: {w.table.rowCount()}")
        if r.n_found:
            print(f"first: {r.eigenvalues[0]:.12g}  last: {r.eigenvalues[-1]:.12g}")
        w.grab().save(str(OUT))
        print(f"screenshot: {OUT}")
        app.quit()
    elif state["ticks"] > 120:  # ~60 s
        print("TIMEOUT: solve never completed")
        w.grab().save(str(OUT))
        app.exit(1)


QTimer.singleShot(600, start)
t = QTimer(); t.timeout.connect(poll); t.start(500)
sys.exit(app.exec())
