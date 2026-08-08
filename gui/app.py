"""FEAST desktop application -- cross-platform GUI over the FEAST eigensolver.

Runs unchanged on Windows, macOS and Linux. The solve happens on a worker
thread so a long run never freezes the window.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow running straight from the source tree without installing.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

import numpy as np
import pyqtgraph as pg
import scipy.sparse as sp
from PySide6.QtCore import Qt, QThread, Signal, Slot
from PySide6.QtGui import QAction, QFont
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog,
    QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QMainWindow,
    QMessageBox, QProgressBar, QPushButton, QSpinBox, QSplitter, QTableWidget,
    QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

import feastpy
from feastpy import matrixio

APP_NAME = "FEAST Eigensolver"


class SolveWorker(QThread):
    """Runs one FEAST solve off the UI thread."""

    finished_ok = Signal(object, float)
    failed = Signal(str)

    def __init__(self, matrix, params: dict):
        super().__init__()
        self.matrix = matrix
        self.params = params

    def run(self):
        import time
        try:
            t0 = time.perf_counter()
            if sp.issparse(self.matrix):
                r = feastpy.eigsh_interval(self.matrix, **self.params)
            else:
                r = feastpy.eigh_interval(self.matrix, **self.params)
            self.finished_ok.emit(r, time.perf_counter() - t0)
        except Exception as exc:  # surfaced in the log pane, not a crash
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1180, 760)

        self.matrix = None
        self.result = None
        self.worker: SolveWorker | None = None

        self._build_ui()
        self._build_menu()
        self._check_library()
        self.load_demo()

    # ---------------------------------------------------------------- UI ----
    def _build_ui(self):
        splitter = QSplitter(Qt.Horizontal)

        # ---- left: controls
        left = QWidget()
        lv = QVBoxLayout(left)

        src = QGroupBox("Matrix")
        sf = QVBoxLayout(src)
        self.demo_combo = QComboBox()
        self.demo_combo.addItems(list(matrixio.DEMOS.keys()))
        self.demo_combo.currentIndexChanged.connect(self.load_demo)
        sf.addWidget(QLabel("Built-in problem:"))
        sf.addWidget(self.demo_combo)
        open_btn = QPushButton("Open matrix file...")
        open_btn.clicked.connect(self.open_file)
        sf.addWidget(open_btn)
        self.matrix_label = QLabel("no matrix loaded")
        self.matrix_label.setWordWrap(True)
        # palette(mid) is nearly invisible on a dark theme; dim the normal text
        # colour by opacity instead so it reads on both light and dark.
        self.matrix_label.setStyleSheet("color: palette(text); opacity: 0.7; font-size: 11px;")
        sf.addWidget(self.matrix_label)
        lv.addWidget(src)

        interval = QGroupBox("Search interval")
        itf = QFormLayout(interval)
        self.emin = QDoubleSpinBox()
        self.emax = QDoubleSpinBox()
        for box, val in ((self.emin, 0.0), (self.emax, 0.02)):
            box.setDecimals(8)
            box.setRange(-1e12, 1e12)
            box.setValue(val)
        itf.addRow("E min", self.emin)
        itf.addRow("E max", self.emax)
        hint = QLabel("FEAST returns every eigenvalue in this interval.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: palette(text); font-size: 11px;")
        itf.addRow(hint)
        lv.addWidget(interval)

        params = QGroupBox("Parameters")
        pf = QFormLayout(params)
        self.m0 = QSpinBox()
        self.m0.setRange(1, 100000)
        self.m0.setValue(40)
        self.m0.setToolTip("Subspace size: an over-estimate of how many\n"
                           "eigenvalues lie in the interval. Too small -> info=3.")
        pf.addRow("Subspace M0", self.m0)

        self.contour = QSpinBox()
        self.contour.setRange(2, 64)
        self.contour.setValue(8)
        self.contour.setToolTip("Quadrature points on the contour. More points =\n"
                                "faster convergence per loop, more work per loop.")
        pf.addRow("Contour points", self.contour)

        self.tol = QSpinBox()
        self.tol.setRange(1, 16)
        self.tol.setValue(12)
        self.tol.setPrefix("1e-")
        pf.addRow("Tolerance", self.tol)

        self.loops = QSpinBox()
        self.loops.setRange(1, 200)
        self.loops.setValue(20)
        pf.addRow("Max loops", self.loops)

        self.auto_m0 = QCheckBox("Retry automatically if M0 is too small")
        self.auto_m0.setChecked(True)
        pf.addRow(self.auto_m0)
        lv.addWidget(params)

        self.solve_btn = QPushButton("Solve")
        self.solve_btn.setMinimumHeight(38)
        f = QFont(); f.setBold(True); self.solve_btn.setFont(f)
        self.solve_btn.clicked.connect(self.solve)
        lv.addWidget(self.solve_btn)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        lv.addWidget(self.progress)

        self.export_btn = QPushButton("Export results (CSV)...")
        self.export_btn.clicked.connect(self.export_csv)
        self.export_btn.setEnabled(False)
        lv.addWidget(self.export_btn)

        lv.addStretch(1)
        left.setMaximumWidth(330)
        splitter.addWidget(left)

        # ---- right: results
        right = QWidget()
        rv = QVBoxLayout(right)

        self.plot = pg.PlotWidget()
        self.plot.setBackground(None)
        self.plot.setLabel("bottom", "eigenvalue")
        self.plot.setLabel("left", "index")
        self.plot.showGrid(x=True, y=True, alpha=0.25)
        rv.addWidget(self.plot, stretch=3)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["#", "eigenvalue", "residual"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        # We render our own "#" column, so Qt's row numbers would be a duplicate.
        self.table.verticalHeader().setVisible(False)
        rv.addWidget(self.table, stretch=4)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(130)
        self.log.setFont(QFont("Consolas" if sys.platform == "win32" else "Menlo", 9))
        rv.addWidget(self.log, stretch=1)

        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)
        self.statusBar().showMessage("ready")

    def _build_menu(self):
        m = self.menuBar().addMenu("&File")
        a = QAction("&Open matrix...", self); a.setShortcut("Ctrl+O")
        a.triggered.connect(self.open_file); m.addAction(a)
        a = QAction("&Export results...", self); a.setShortcut("Ctrl+S")
        a.triggered.connect(self.export_csv); m.addAction(a)
        m.addSeparator()
        a = QAction("E&xit", self); a.setShortcut("Ctrl+Q")
        a.triggered.connect(self.close); m.addAction(a)

        h = self.menuBar().addMenu("&Help")
        a = QAction("&About", self)
        a.triggered.connect(self.about); h.addAction(a)

    # ------------------------------------------------------------ actions ----
    def _log(self, msg: str):
        self.log.append(msg)

    def _check_library(self):
        try:
            feastpy.load()
            self._log("libfeast loaded")
        except feastpy.FeastLibraryNotFound as exc:
            self._log(str(exc))
            QMessageBox.critical(self, APP_NAME,
                                 "The FEAST native library could not be loaded.\n\n"
                                 f"{exc}")
            self.solve_btn.setEnabled(False)

    @Slot()
    def load_demo(self):
        name = self.demo_combo.currentText()
        build, emin, emax = matrixio.DEMOS[name]
        self.matrix = build()
        self.emin.setValue(emin)
        self.emax.setValue(emax)
        self.matrix_label.setText(matrixio.describe(self.matrix))
        self._log(f"loaded demo: {name}")

    @Slot()
    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open matrix", "",
                                              matrixio.SUPPORTED)
        if not path:
            return
        try:
            M = matrixio.load_matrix(path)
        except matrixio.MatrixLoadError as exc:
            QMessageBox.warning(self, APP_NAME, str(exc)); return

        if M.shape[0] != M.shape[1]:
            QMessageBox.warning(self, APP_NAME,
                                f"Matrix must be square, got {M.shape[0]}x{M.shape[1]}.")
            return

        sym, herm = matrixio.check_symmetry(M)
        if not (sym or herm):
            QMessageBox.warning(
                self, APP_NAME,
                "This matrix is neither symmetric nor Hermitian.\n\n"
                "The solvers wired up here require one of those. "
                "Results would be meaningless.")
            return

        self.matrix = M
        self.matrix_label.setText(matrixio.describe(M))
        self._log(f"loaded {Path(path).name}: {matrixio.describe(M)}")

    @Slot()
    def solve(self):
        if self.matrix is None:
            return
        if self.emin.value() >= self.emax.value():
            QMessageBox.warning(self, APP_NAME, "E min must be less than E max.")
            return

        params = dict(
            emin=self.emin.value(),
            emax=self.emax.value(),
            m0=self.m0.value(),
            contour_points=self.contour.value(),
            tol_exponent=self.tol.value(),
            max_loops=self.loops.value(),
        )
        self._log(f"solving on [{params['emin']:g}, {params['emax']:g}] "
                  f"with M0={params['m0']}...")
        self.solve_btn.setEnabled(False)
        self.progress.show()
        self.statusBar().showMessage("solving...")

        self.worker = SolveWorker(self.matrix, params)
        self.worker.finished_ok.connect(self.on_solved)
        self.worker.failed.connect(self.on_failed)
        self.worker.start()

    @Slot(object, float)
    def on_solved(self, r, secs: float):
        # info=3 means the subspace was too small to hold the whole interval;
        # doubling M0 and retrying is exactly what a user would do by hand.
        if r.info == 3 and self.auto_m0.isChecked():
            new_m0 = min(self.m0.value() * 2, self.matrix.shape[0])
            if new_m0 > self.m0.value():
                self._log(f"  M0 too small; retrying with M0={new_m0}")
                self.m0.setValue(new_m0)
                self.solve()
                return

        self.progress.hide()
        self.solve_btn.setEnabled(True)
        self.result = r

        self._log(f"  info={r.info} ({r.message})")
        self._log(f"  found {r.n_found} eigenvalues in {r.loops} loop(s), "
                  f"epsout={r.epsout:.2e}, {secs:.2f}s")
        self.statusBar().showMessage(
            f"{r.n_found} eigenvalues  |  {secs:.2f}s  |  {r.message}")

        self.table.setRowCount(r.n_found)
        for i in range(r.n_found):
            for col, text in ((0, str(i + 1)),
                              (1, f"{r.eigenvalues[i]:.12g}"),
                              (2, f"{r.residuals[i]:.3e}")):
                item = QTableWidgetItem(text)
                if col:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(i, col, item)

        self.plot.clear()
        if r.n_found:
            self.plot.plot(r.eigenvalues, np.arange(1, r.n_found + 1),
                           pen=None, symbol="o", symbolSize=7,
                           symbolBrush=(70, 130, 220))
        for x in (self.emin.value(), self.emax.value()):
            self.plot.addLine(x=x, pen=pg.mkPen((200, 80, 80), style=Qt.DashLine))

        self.export_btn.setEnabled(r.n_found > 0)

        if r.info not in (0, 1):
            QMessageBox.information(self, APP_NAME,
                                    f"FEAST returned info={r.info}:\n\n{r.message}")

    @Slot(str)
    def on_failed(self, msg: str):
        self.progress.hide()
        self.solve_btn.setEnabled(True)
        self.statusBar().showMessage("failed")
        self._log(f"  ERROR {msg}")
        QMessageBox.critical(self, APP_NAME, msg)

    @Slot()
    def export_csv(self):
        if self.result is None or not self.result.n_found:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export results",
                                              "eigenvalues.csv", "CSV (*.csv)")
        if not path:
            return
        r = self.result
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("index,eigenvalue,residual\n")
            for i in range(r.n_found):
                fh.write(f"{i + 1},{r.eigenvalues[i]!r},{r.residuals[i]!r}\n")
        self._log(f"wrote {path}")
        self.statusBar().showMessage(f"exported to {path}")

    def about(self):
        QMessageBox.about(
            self, f"About {APP_NAME}",
            f"<b>{APP_NAME}</b><br>"
            f"Front end for the FEAST eigenvalue solver, v4.0.<br><br>"
            "FEAST is copyright (c) 2009-2020 The Regents of the University of "
            "Massachusetts, Amherst (E. Polizzi research lab), and is "
            "distributed under the BSD license.")


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
