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
from PySide6.QtCore import Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QAction, QFont
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog,
    QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QMainWindow,
    QMessageBox, QProgressBar, QPushButton, QSpinBox, QSplitter, QTableWidget,
    QTableWidgetItem, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

import feastpy
from feastpy import codegen, matrixio, results_io, runner

APP_NAME = "FEAST Eigensolver"


class SolveWorker(QThread):
    """Supervises one FEAST solve.

    The solve itself runs in a child process (see feastpy.runner): a FEAST call
    is one blocking trip into Fortran with no abort hook, so terminating the
    process is the only way to make Cancel actually stop the work rather than
    just hiding it. This thread waits on that process and keeps the UI live.
    """

    finished_ok = Signal(object, float)
    failed = Signal(str)
    cancelled = Signal()
    tick = Signal(float)          # seconds elapsed, for the status bar
    progress = Signal(dict)       # one row of FEAST's convergence table

    def __init__(self, matrix, b_matrix, params: dict):
        super().__init__()
        self.matrix = matrix
        self.b_matrix = b_matrix
        self.params = params
        self.handle = None
        self._cancel = False

    def cancel(self):
        self._cancel = True
        if self.handle is not None:
            self.handle.cancel()

    def run(self):
        import time
        try:
            self.handle = runner.start_solve(self.matrix, self.b_matrix, self.params)
        except Exception as exc:
            self.failed.emit(f"could not start solver process: {exc}")
            return

        t0 = time.perf_counter()
        while True:
            if self._cancel:
                self.handle.cancel()
                self.handle.close()
                self.cancelled.emit()
                return
            out = self.handle.poll(timeout=0.15)
            if out is None:
                self.tick.emit(time.perf_counter() - t0)
                continue
            if out[0] == "progress":
                self.progress.emit(out[1])
                continue
            kind, payload, secs = out
            self.handle.close()
            if self._cancel:              # finished as we were cancelling
                self.cancelled.emit()
            elif kind == "ok":
                self.finished_ok.emit(payload, secs)
            else:
                self.failed.emit(payload)
            return


class CountWorker(QThread):
    """Stochastic eigenvalue-count estimate -- typically 100x+ faster than a
    full solve, which is what makes 'how many are in here?' answerable
    interactively while the user drags the interval around."""

    finished_ok = Signal(int, float)
    failed = Signal(str)

    def __init__(self, matrix, emin, emax, contour_points, b_matrix=None):
        super().__init__()
        self.matrix, self.emin, self.emax = matrix, emin, emax
        self.contour_points = contour_points
        self.b_matrix = b_matrix

    def run(self):
        import time
        try:
            t0 = time.perf_counter()
            n = feastpy.estimate_count(self.matrix, self.emin, self.emax,
                                       self.b_matrix,
                                       contour_points=self.contour_points)
            self.finished_ok.emit(int(n), time.perf_counter() - t0)
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class CodeDialog(QDialog):
    """Shows the current problem as source code.

    Displayed rather than copied silently: users need to read it before trusting
    it, and it doubles as documentation of which FEAST routine the settings map
    to -- the part that is easy to get wrong by hand.
    """

    def __init__(self, spec, parent=None):
        super().__init__(parent)
        self.spec = spec
        self.setWindowTitle("Copy as code")
        self.resize(820, 620)

        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(QLabel("Language:"))
        self.lang = QComboBox()
        self.lang.addItems(list(codegen.GENERATORS.keys()))
        self.lang.currentIndexChanged.connect(self.regenerate)
        row.addWidget(self.lang)
        row.addStretch(1)
        self.routine = QLabel()
        self.routine.setStyleSheet("color: palette(text); font-size: 11px;")
        row.addWidget(self.routine)
        lay.addLayout(row)

        self.text = QTextEdit()
        self.text.setReadOnly(True)
        self.text.setLineWrapMode(QTextEdit.NoWrap)
        self.text.setFont(QFont("Consolas" if sys.platform == "win32" else "Menlo", 10))
        lay.addWidget(self.text, stretch=1)

        buttons = QHBoxLayout()
        self.copy_btn = QPushButton("Copy to clipboard")
        self.copy_btn.clicked.connect(self.copy)
        buttons.addWidget(self.copy_btn)
        save_btn = QPushButton("Save as...")
        save_btn.clicked.connect(self.save)
        buttons.addWidget(save_btn)
        buttons.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        buttons.addWidget(close_btn)
        lay.addLayout(buttons)

        self.regenerate()

    def regenerate(self):
        gen = codegen.GENERATORS[self.lang.currentText()]
        self.text.setPlainText(gen(self.spec))
        self.routine.setText(f"FEAST routine: {codegen.routine_name(self.spec)}")

    def copy(self):
        QApplication.clipboard().setText(self.text.toPlainText())
        self.copy_btn.setText("Copied")
        QTimer.singleShot(1200, lambda: self.copy_btn.setText("Copy to clipboard"))

    def save(self):
        ext = ".py" if self.lang.currentText().startswith("Python") else ".c"
        path, _ = QFileDialog.getSaveFileName(self, "Save code", f"feast_solve{ext}",
                                              f"Source (*{ext})")
        if path:
            Path(path).write_text(self.text.toPlainText(), encoding="utf-8")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1180, 760)

        self.matrix = None
        self.b_matrix = None
        self.matrix_path = None
        self.b_path = None
        self.result = None
        self.bounds = None
        self.convergence = []
        self._syncing = False
        self.solving = False
        self.worker: SolveWorker | None = None
        self.counter: CountWorker | None = None

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

        # B matrix: A x = lambda B x. Optional -- absent means the standard
        # problem. Many real problems (and FEAST's own samples) are generalized.
        brow = QHBoxLayout()
        self.open_b_btn = QPushButton("Open B matrix...")
        self.open_b_btn.setToolTip("For the generalized problem A x = λ B x.\n"
                                   "B must be positive definite.")
        self.open_b_btn.clicked.connect(self.open_b_file)
        brow.addWidget(self.open_b_btn)
        self.clear_b_btn = QPushButton("Clear B")
        self.clear_b_btn.clicked.connect(self.clear_b)
        self.clear_b_btn.setEnabled(False)
        brow.addWidget(self.clear_b_btn)
        sf.addLayout(brow)

        self.b_label = QLabel("no B - standard problem A x = λ x")
        self.b_label.setWordWrap(True)
        self.b_label.setStyleSheet("color: palette(text); font-size: 11px;")
        sf.addWidget(self.b_label)
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
        self.emin.valueChanged.connect(self._spins_to_region)
        self.emax.valueChanged.connect(self._spins_to_region)

        self.range_label = QLabel("spectrum range: unknown")
        self.range_label.setWordWrap(True)
        self.range_label.setStyleSheet("color: palette(text); font-size: 11px;")
        itf.addRow(self.range_label)

        self.full_range_btn = QPushButton("Use whole spectrum")
        self.full_range_btn.setToolTip("Set the interval to the Gershgorin bounds, "
                                       "which are guaranteed to contain every eigenvalue.")
        self.full_range_btn.clicked.connect(self.use_full_range)
        itf.addRow(self.full_range_btn)

        self.count_btn = QPushButton("How many are in here?")
        self.count_btn.setToolTip("Stochastic estimate of the eigenvalue count.\n"
                                  "Much faster than solving, and sets M0 for you.")
        self.count_btn.clicked.connect(self.estimate_count)
        itf.addRow(self.count_btn)

        self.count_label = QLabel("drag the shaded band on the plot to choose an interval")
        self.count_label.setWordWrap(True)
        self.count_label.setStyleSheet("color: palette(text); font-size: 11px;")
        itf.addRow(self.count_label)

        self.zoom_out_btn = QPushButton("Zoom out to full spectrum")
        self.zoom_out_btn.setToolTip("Solving zooms the plot to the interval; "
                                     "this returns to the whole spectral range.")
        self.zoom_out_btn.clicked.connect(self.zoom_full)
        self.zoom_out_btn.setEnabled(False)
        itf.addRow(self.zoom_out_btn)
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
        self.solve_btn.clicked.connect(self.on_solve_button)
        lv.addWidget(self.solve_btn)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        lv.addWidget(self.progress)

        self.code_btn = QPushButton("Copy as code...")
        self.code_btn.setToolTip("Emit this exact problem as a runnable Python "
                                 "or C program.")
        self.code_btn.clicked.connect(self.show_code)
        lv.addWidget(self.code_btn)

        self.export_btn = QPushButton("Export results...")
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

        # The draggable search interval. This is the core interaction: FEAST
        # asks for a range, and typing two numbers blind is the single biggest
        # source of empty results. Dragging a band over the known spectral
        # bounds turns that guess into a choice.
        self.region = pg.LinearRegionItem(values=(0.0, 0.02),
                                          brush=pg.mkBrush(70, 130, 220, 45),
                                          hoverBrush=pg.mkBrush(70, 130, 220, 70))
        self.region.setZValue(-10)
        self.region.sigRegionChanged.connect(self._region_to_spins)
        self.plot.addItem(self.region)

        self.conv_plot = pg.PlotWidget()
        self.conv_plot.setBackground(None)
        self.conv_plot.setLabel("bottom", "refinement loop")
        self.conv_plot.setLabel("left", "error")
        self.conv_plot.setLogMode(y=True)      # errors span many decades
        self.conv_plot.showGrid(x=True, y=True, alpha=0.25)
        self.conv_plot.addLegend(offset=(-10, 10))

        self.tabs = QTabWidget()
        self.tabs.addTab(self.plot, "Spectrum")
        self.tabs.addTab(self.conv_plot, "Convergence")
        rv.addWidget(self.tabs, stretch=3)

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

    # -- interval <-> plot band -------------------------------------------
    # Both directions write to the other, so a guard breaks the feedback loop.
    def _region_to_spins(self):
        if self._syncing:
            return
        self._syncing = True
        try:
            lo, hi = self.region.getRegion()
            self.emin.setValue(lo)
            self.emax.setValue(hi)
            self.count_label.setText("interval changed - estimate again")
        finally:
            self._syncing = False

    def _spins_to_region(self):
        if self._syncing:
            return
        self._syncing = True
        try:
            self.region.setRegion((self.emin.value(), self.emax.value()))
        finally:
            self._syncing = False

    def _update_spectrum_view(self):
        """Gershgorin-bound the spectrum so the user can see where to look."""
        if self.matrix is None:
            return
        try:
            lo, hi = feastpy.spectral_bounds(self.matrix, self.b_matrix)
        except Exception as exc:
            self.range_label.setText(f"spectrum range: unavailable ({exc})")
            return

        self.bounds = (lo, hi)
        kind = "pencil bound" if self.b_matrix is not None else "Gershgorin bound"
        # Two lines, not three: a third gets clipped by the group box.
        self.range_label.setText(f"all eigenvalues lie in\n[{lo:.6g}, {hi:.6g}]")
        self.range_label.setToolTip(
            f"{kind}: guaranteed to contain every eigenvalue, but not tight.")
        # The count belongs to the previous problem; leaving it up is a lie.
        self.count_label.setText("drag the shaded band on the plot to choose an interval")
        pad = 0.02 * (hi - lo)
        self.plot.setXRange(lo - pad, hi + pad)
        self._spins_to_region()

    @Slot()
    def zoom_full(self):
        if self.bounds is None:
            return
        lo, hi = self.bounds
        pad = 0.02 * (hi - lo) or 1e-9
        self.plot.setXRange(lo - pad, hi + pad)

    @Slot()
    def use_full_range(self):
        if self.bounds is None:
            return
        lo, hi = self.bounds
        self.emin.setValue(lo)
        self.emax.setValue(hi)

    @Slot()
    def estimate_count(self):
        if self.matrix is None or self.emin.value() >= self.emax.value():
            return
        self.count_btn.setEnabled(False)
        self.count_label.setText("estimating...")
        self.counter = CountWorker(self.matrix, self.emin.value(), self.emax.value(),
                                   self.contour.value(), self.b_matrix)
        self.counter.finished_ok.connect(self.on_counted)
        self.counter.failed.connect(self.on_count_failed)
        self.counter.start()

    @Slot(int, float)
    def on_counted(self, n: int, secs: float):
        self.count_btn.setEnabled(True)
        self.count_label.setText(f"about {n} eigenvalue(s) in this interval  ({secs:.2f}s)")
        self._log(f"estimated {n} eigenvalues in "
                  f"[{self.emin.value():g}, {self.emax.value():g}] in {secs:.2f}s")
        if n > 0:
            # The estimate is stochastic, so size the subspace above it rather
            # than at it; too small costs a whole extra refinement cycle.
            suggested = min(self.matrix.shape[0], max(10, int(n * 1.5) + 5))
            self.m0.setValue(suggested)
            self._log(f"  set M0 = {suggested}")
        else:
            self.count_label.setText("about 0 eigenvalues here - try a wider interval")

    @Slot(str)
    def on_count_failed(self, msg: str):
        self.count_btn.setEnabled(True)
        self.count_label.setText("estimate failed")
        self._log(f"  ERROR {msg}")

    @Slot()
    def load_demo(self):
        name = self.demo_combo.currentText()
        build, emin, emax = matrixio.DEMOS[name]
        built = build()
        # Demos backed by files on disk report their paths so generated code
        # can load the same matrices; generated ones leave a placeholder.
        self.matrix_path, self.b_path = matrixio.demo_paths(name)
        self.b_matrix = None
        self.clear_b_btn.setEnabled(False)
        self.b_label.setText("no B - standard problem A x = λ x")
        if isinstance(built, tuple):
            self.matrix, b = built
        else:
            self.matrix, b = built, None
        self.emin.setValue(emin)
        self.emax.setValue(emax)
        self.matrix_label.setText(matrixio.describe(self.matrix))
        if b is not None:
            demo_b = self.b_path
            self._set_b(b, "paired with demo")
            self.b_path = demo_b
        self._update_spectrum_view()
        self._log(f"loaded demo: {name}")

    def _set_b(self, B, origin: str):
        """Adopt B after checking it can actually serve as the mass matrix."""
        if B.shape != self.matrix.shape:
            QMessageBox.warning(self, APP_NAME,
                                f"B is {B.shape[0]}x{B.shape[1]} but A is "
                                f"{self.matrix.shape[0]}x{self.matrix.shape[1]}. "
                                "They must match.")
            return False

        sym, herm = matrixio.check_symmetry(B)
        if not (sym or herm):
            QMessageBox.warning(self, APP_NAME,
                                "B is neither symmetric nor Hermitian, so the "
                                "generalized problem is not defined.")
            return False

        if not matrixio.is_probably_spd(B):
            # FEAST requires spd B; carrying on would give silent nonsense.
            QMessageBox.warning(
                self, APP_NAME,
                "B does not look positive definite.\n\n"
                "FEAST's generalized interfaces require an spd B. Results would "
                "not be meaningful, so this matrix was not loaded.")
            return False

        self.b_matrix = B
        self.b_label.setText(f"B: {matrixio.describe(B)}  ({origin})")
        self.clear_b_btn.setEnabled(True)
        self._update_spectrum_view()
        self._log(f"loaded B ({origin}): {matrixio.describe(B)}")
        return True

    @Slot()
    def clear_b(self):
        self.b_matrix = None
        self.b_label.setText("no B - standard problem A x = λ x")
        self.clear_b_btn.setEnabled(False)
        self._update_spectrum_view()
        self._log("cleared B; solving the standard problem")

    @Slot()
    def open_b_file(self):
        if self.matrix is None:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open B matrix", "",
                                              matrixio.SUPPORTED)
        if not path:
            return
        try:
            B = matrixio.load_matrix(path)
        except matrixio.MatrixLoadError as exc:
            QMessageBox.warning(self, APP_NAME, str(exc)); return
        if self._set_b(B, Path(path).name):
            self.b_path = path

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
        self.matrix_path = path
        self.b_matrix = None
        self.b_path = None
        self.clear_b_btn.setEnabled(False)
        self.b_label.setText("no B - standard problem A x = λ x")
        self.matrix_label.setText(matrixio.describe(M))
        self._update_spectrum_view()
        self._log(f"loaded {Path(path).name}: {matrixio.describe(M)}")

        # FEAST names generalized pairs system1.mtx / system1B.mtx, so offer
        # the partner rather than making the user go find it.
        partner = matrixio.guess_b_path(path)
        if partner is not None:
            ans = QMessageBox.question(
                self, APP_NAME,
                f"Found {partner.name} beside this matrix.\n\n"
                "Load it as B and solve the generalized problem A x = λ B x?")
            if ans == QMessageBox.Yes:
                try:
                    if self._set_b(matrixio.load_matrix(partner), partner.name):
                        self.b_path = str(partner)
                except matrixio.MatrixLoadError as exc:
                    QMessageBox.warning(self, APP_NAME, str(exc))

    @Slot()
    def on_solve_button(self):
        """The Solve button becomes Cancel while a solve is running."""
        if self.solving:
            self.cancel_solve()
        else:
            self.solve()

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
        if not self.solving:          # a fresh solve, not an auto-retry
            self.convergence = []
            self.conv_plot.clear()
        self._log(f"solving on [{params['emin']:g}, {params['emax']:g}] "
                  f"with M0={params['m0']}...")
        self._set_solving(True)
        self.statusBar().showMessage("solving...")

        self.worker = SolveWorker(self.matrix, self.b_matrix, params)
        self.worker.finished_ok.connect(self.on_solved)
        self.worker.failed.connect(self.on_failed)
        self.worker.cancelled.connect(self.on_cancelled)
        self.worker.tick.connect(self.on_tick)
        self.worker.progress.connect(self.on_progress)
        self.worker.start()

    def _set_solving(self, solving: bool):
        """Swap Solve for Cancel; they are the same button so the action is
        always where the user just clicked."""
        self.solving = solving
        self.solve_btn.setText("Cancel" if solving else "Solve")
        self.progress.setVisible(solving)
        for w in (self.count_btn, self.full_range_btn, self.demo_combo,
                  self.open_b_btn):
            w.setEnabled(not solving)

    @Slot(dict)
    def on_progress(self, rec: dict):
        """One row of FEAST's convergence table arrived. Plotting these turns
        'it is still going' into 'it is converging, and how fast'."""
        self.convergence.append(rec)
        loops = [r["loop"] for r in self.convergence]

        # Log axis: zeros are exact convergence and cannot be plotted, so floor
        # them just under the smallest real value rather than dropping points.
        def series(key):
            vals = [r[key] for r in self.convergence]
            nz = [v for v in vals if v > 0]
            floor = min(nz) / 10 if nz else 1e-16
            return [v if v > 0 else floor for v in vals]

        self.conv_plot.clear()
        self.conv_plot.plot(loops, series("error_trace"), name="trace error",
                            pen=pg.mkPen((70, 130, 220), width=2),
                            symbol="o", symbolSize=6, symbolBrush=(70, 130, 220))
        self.conv_plot.plot(loops, series("residual"), name="max residual",
                            pen=pg.mkPen((220, 130, 70), width=2),
                            symbol="t", symbolSize=6, symbolBrush=(220, 130, 70))
        tol = 10.0 ** (-self.tol.value())
        self.conv_plot.addLine(y=np.log10(tol),
                               pen=pg.mkPen((150, 150, 150), style=Qt.DashLine))

        self.statusBar().showMessage(
            f"loop {rec['loop']}: {rec['n_eig']} eigenvalues, "
            f"residual {rec['residual']:.2e}   (press Cancel to stop)")

    @Slot(float)
    def on_tick(self, secs: float):
        self.statusBar().showMessage(f"solving... {secs:.1f}s   (press Cancel to stop)")

    @Slot()
    def cancel_solve(self):
        if self.worker is None:
            return
        self._log("  cancelling...")
        self.statusBar().showMessage("cancelling...")
        self.solve_btn.setEnabled(False)
        self.worker.cancel()

    @Slot()
    def on_cancelled(self):
        self.solve_btn.setEnabled(True)
        self._set_solving(False)
        self._log("  cancelled")
        self.statusBar().showMessage("cancelled")

    @Slot(object, float)
    def on_solved(self, r, secs: float):
        # info=3 means the subspace was too small to hold the whole interval;
        # doubling M0 and retrying is exactly what a user would do by hand.
        if r.info == 3 and self.auto_m0.isChecked():
            new_m0 = min(self.m0.value() * 2, self.matrix.shape[0])
            if new_m0 > self.m0.value():
                self._log(f"  M0 too small; retrying with M0={new_m0}")
                self.m0.setValue(new_m0)
                self._set_solving(False)
                self.solve()
                return

        self._set_solving(False)
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
        self.plot.addItem(self.region)      # clear() drops it otherwise
        if r.n_found:
            self.plot.plot(r.eigenvalues, np.arange(1, r.n_found + 1),
                           pen=None, symbol="o", symbolSize=7,
                           symbolBrush=(70, 130, 220))
            # Zoom to the interval that was solved. The axis was showing the
            # whole Gershgorin range for exploring, and a narrow interval's
            # results are an unreadable sliver at that scale.
            lo, hi = self.emin.value(), self.emax.value()
            pad = 0.08 * (hi - lo) or 1e-9
            self.plot.setXRange(lo - pad, hi + pad)
            self.zoom_out_btn.setEnabled(self.bounds is not None)
        self.export_btn.setEnabled(r.n_found > 0)

        if r.info not in (0, 1):
            QMessageBox.information(self, APP_NAME,
                                    f"FEAST returned info={r.info}:\n\n{r.message}")

    @Slot(str)
    def on_failed(self, msg: str):
        self._set_solving(False)
        self.solve_btn.setEnabled(True)
        self.statusBar().showMessage("failed")
        self._log(f"  ERROR {msg}")
        QMessageBox.critical(self, APP_NAME, msg)

    def _code_spec(self):
        """The current problem as a ProblemSpec."""
        return codegen.ProblemSpec(
            n=int(self.matrix.shape[0]),
            sparse=sp.issparse(self.matrix),
            complex=bool(np.iscomplexobj(self.matrix.data if sp.issparse(self.matrix)
                                         else self.matrix)),
            generalized=self.b_matrix is not None,
            # Mirror the defaults feastpy uses for each path, so the generated
            # code reproduces this run rather than a differently-stored one.
            uplo="U" if sp.issparse(self.matrix) else "F",
            emin=self.emin.value(), emax=self.emax.value(),
            m0=self.m0.value(), contour_points=self.contour.value(),
            tol_exponent=self.tol.value(), max_loops=self.loops.value(),
            iterative=True,
            matrix_path=self.matrix_path, b_path=self.b_path,
        )

    @Slot()
    def show_code(self):
        if self.matrix is None:
            return
        CodeDialog(self._code_spec(), self).exec()

    @Slot()
    def export_csv(self):
        """Export results. The format picker is the file-type filter."""
        if self.result is None or not self.result.n_found:
            return

        path, selected = QFileDialog.getSaveFileName(
            self, "Export results", "eigen_results.npz", results_io.FORMAT_LABELS)
        if not path:
            return

        fmt = results_io.format_for_label(selected)
        path = Path(path)
        if not path.suffix:
            path = path.with_suffix(results_io.extension_for(fmt))

        # A dense eigenvector block is n x m; as text that gets big enough to
        # be worth a warning rather than a surprise.
        cells = results_io.estimate_cells(self.result, fmt)
        if fmt in ("vectors-csv", "mtx") and cells > 2_000_000:
            ans = QMessageBox.question(
                self, APP_NAME,
                f"This writes about {cells:,} numbers as text, which may be slow "
                "and produce a very large file.\n\n"
                "The NumPy (.npz) format stores the same data compressed. "
                "Continue anyway?")
            if ans != QMessageBox.Yes:
                return

        try:
            written = results_io.save_results(path, self.result, fmt,
                                              emin=self.emin.value(),
                                              emax=self.emax.value())
        except Exception as exc:
            QMessageBox.critical(self, APP_NAME, f"Export failed:\n\n{exc}")
            self._log(f"  ERROR export: {exc}")
            return

        what = ("eigenvalues only" if fmt == "values-csv"
                else f"{self.result.n_found} eigenvalues + eigenvectors")
        self._log(f"wrote {written}  ({what})")
        self.statusBar().showMessage(f"exported {what} to {written}")

    def about(self):
        QMessageBox.about(
            self, f"About {APP_NAME}",
            f"<b>{APP_NAME}</b><br>"
            f"Front end for the FEAST eigenvalue solver, v4.0.<br><br>"
            "FEAST is copyright (c) 2009-2020 The Regents of the University of "
            "Massachusetts, Amherst (E. Polizzi research lab), and is "
            "distributed under the BSD license.")


def main():
    # Solves run in a child process. In a bundled app sys.executable is this
    # program, so the child would relaunch the GUI; the flag routes it to the
    # worker instead. Harmless when running from source, where the child is
    # started as `python -m feastpy._solve_child`.
    import os
    if getattr(sys, "frozen", False) and os.environ.get(runner.CHILD_ENV_FLAG):
        from feastpy import _solve_child
        return _solve_child.main(sys.argv[1:])

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
