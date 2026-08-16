"""FEAST desktop application -- cross-platform GUI over the FEAST eigensolver.

Runs unchanged on Windows, macOS and Linux. The solve happens on a worker
thread so a long run never freezes the window.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow running straight from the source tree without installing.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pyqtgraph as pg
import scipy.sparse as sp
from PySide6.QtCore import Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QAction, QFont
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog,
    QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QMainWindow,
    QMessageBox, QProgressBar, QPushButton, QSpinBox, QSplitter, QTableWidget,
    QScrollArea, QStackedWidget, QTableWidgetItem, QTabWidget, QTextEdit,
    QVBoxLayout, QWidget,
)

import licensing
import feastpy
from feastpy import (algorithms, codegen, contours, diagnostics, matrixio,
                     problems, raw, results_io, runner)
from views import (ComplexSpectrumView, EigenvectorView, FilterView,
                   MatrixView, SpectrumView)

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


class LicenseDialog(QDialog):
    """Show licence status, and take a pasted key.

    The machine id is front and centre and selectable: a machine-locked licence
    cannot be issued without it, so the buyer has to be able to send it easily.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Licence")
        self.resize(620, 420)
        lay = QVBoxLayout(self)

        self.status = QLabel()
        self.status.setWordWrap(True)
        lay.addWidget(self.status)

        box = QGroupBox("This computer")
        bl = QVBoxLayout(box)
        mid = QTextEdit()
        mid.setReadOnly(True)
        mid.setMaximumHeight(34)
        mid.setPlainText(licensing.machine_id())
        mid.setFont(QFont("Consolas" if sys.platform == "win32" else "Menlo", 11))
        bl.addWidget(QLabel("Send this id when buying, so the licence can be "
                            "issued for this machine:"))
        bl.addWidget(mid)
        lay.addWidget(box)

        lay.addWidget(QLabel("Paste your licence key:"))
        self.entry = QTextEdit()
        self.entry.setFont(QFont("Consolas" if sys.platform == "win32" else "Menlo", 9))
        lay.addWidget(self.entry, stretch=1)

        row = QHBoxLayout()
        self.apply_btn = QPushButton("Activate")
        self.apply_btn.clicked.connect(self.activate)
        row.addWidget(self.apply_btn)
        self.remove_btn = QPushButton("Remove licence")
        self.remove_btn.clicked.connect(self.remove)
        row.addWidget(self.remove_btn)
        row.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        lay.addLayout(row)

        self.refresh()

    def refresh(self):
        if not licensing.ENABLED:
            self.status.setText(f"<b>Unrestricted build.</b><br>{licensing.why_disabled()}")
            self.entry.setEnabled(False)
            self.apply_btn.setEnabled(False)
            self.remove_btn.setEnabled(False)
            return
        st = licensing.load()
        if st.licensed:
            self.status.setText(
                f"<b>Licensed</b> to {st.holder}<br>"
                f"Updates included until {st.license.updates_until}.")
        else:
            extra = f"<br><span style='color:#c0392b'>{st.error}</span>" if st.error else ""
            self.status.setText(
                "<b>Free version.</b> Everything works; problem size is capped at "
                f"{licensing.FREE_DENSE_N:,} dense / {licensing.FREE_SPARSE_N:,} "
                f"sparse.{extra}")
        self.remove_btn.setEnabled(st.licensed)

    def activate(self):
        try:
            st = licensing.install(self.entry.toPlainText())
        except licensing.LicenseError as exc:
            QMessageBox.warning(self, APP_NAME, str(exc))
            return
        QMessageBox.information(self, APP_NAME,
                                f"Thank you. Licensed to {st.holder}.")
        self.entry.clear()
        self.refresh()
        if self.parent():
            self.parent().refresh_license()

    def remove(self):
        if QMessageBox.question(self, APP_NAME,
                                "Remove the licence from this computer?") == QMessageBox.Yes:
            licensing.remove()
            self.refresh()
            if self.parent():
                self.parent().refresh_license()


class GenerateDialog(QDialog):
    """Make a random test matrix without needing a file.

    Useful for trying the app out, and for producing a problem of a chosen size
    when you want to see how it behaves on something bigger than the demos.
    """

    KINDS = ["sparse symmetric", "dense symmetric", "dense complex Hermitian"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Generate a random matrix")
        self.result_matrices = None

        form = QFormLayout(self)
        self.kind = QComboBox()
        self.kind.addItems(self.KINDS)
        self.kind.currentIndexChanged.connect(self._sync)
        form.addRow("Type", self.kind)

        self.n = QSpinBox()
        self.n.setRange(2, 200_000)
        self.n.setValue(2000)
        form.addRow("Size n", self.n)

        self.density = QDoubleSpinBox()
        self.density.setDecimals(5)
        self.density.setRange(0.00001, 1.0)
        self.density.setSingleStep(0.0005)
        self.density.setValue(0.001)
        form.addRow("Density", self.density)

        self.generalized = QCheckBox("also generate a positive definite B")
        form.addRow(self.generalized)

        self.seed = QSpinBox()
        self.seed.setRange(-1, 2_000_000_000)
        self.seed.setValue(-1)
        self.seed.setSpecialValueText("random each time")
        self.seed.setToolTip("Set a seed to reproduce the same matrix again.")
        form.addRow("Seed", self.seed)

        self.warn = QLabel()
        self.warn.setWordWrap(True)
        self.warn.setStyleSheet("color: palette(text); font-size: 11px;")
        form.addRow(self.warn)

        row = QHBoxLayout()
        ok = QPushButton("Generate")
        ok.setDefault(True)
        ok.clicked.connect(self.generate)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(ok)
        form.addRow(row)

        self.n.valueChanged.connect(self._sync)
        self.density.valueChanged.connect(self._sync)
        self._sync()

    def _sync(self):
        sparse = self.kind.currentText().startswith("sparse")
        self.density.setEnabled(sparse)
        n = self.n.value()
        if not sparse:
            # A dense matrix is n^2 doubles and the solve is O(n^3); saying so
            # beats letting someone type 50000 and wait for the swap file.
            mb = n * n * 8 / 1e6
            self.warn.setText(f"Dense: about {mb:,.0f} MB of memory."
                              + ("  That is a lot - consider sparse." if mb > 500 else ""))
        else:
            nnz = max(n, int(self.density.value() * n * n / 2)) * 2
            self.warn.setText(f"Sparse: roughly {nnz:,} nonzeros.")

    def generate(self):
        seed = None if self.seed.value() < 0 else self.seed.value()
        n = self.n.value()
        kind = self.kind.currentText()
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            if kind.startswith("sparse"):
                A = matrixio.random_sparse_symmetric(n, self.density.value(), seed)
            elif "Hermitian" in kind:
                A = matrixio.random_hermitian(n, seed)
            else:
                A = matrixio.random_symmetric(n, seed if seed is not None else 0)
            B = None
            if self.generalized.isChecked():
                B = matrixio.random_spd(n, sparse=kind.startswith("sparse"), seed=seed)
            self.result_matrices = (A, B, f"random {kind}, n={n}"
                                    + (f", seed={seed}" if seed is not None else ""))
        except MemoryError:
            QMessageBox.warning(self, APP_NAME,
                                "Not enough memory for a matrix that size. "
                                "Try a smaller n, or the sparse type.")
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.accept()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1180, 760)
        # Fit on a 1366x768 laptop, the common worst case.
        self.setMinimumSize(880, 560)

        self.matrix = None
        self.b_matrix = None
        self.matrix_path = None
        self.b_path = None
        self.result = None
        # How the matrix in hand is stored, and therefore what we must tell
        # FEAST. Recomputed from the data on every load: declaring 'L' for a
        # full matrix makes FEAST count off-diagonals twice, and declaring 'F'
        # for a half-stored one silently discards half the problem. Neither
        # raises an error.
        self._uplo = "F"
        # Which kind of search region is in force. A Hermitian matrix has real
        # eigenvalues, so an interval on the real line finds them; a
        # non-Hermitian one scatters them across the complex plane and needs a
        # disc. This is a property of the matrix, not a user preference.
        self._geometry = problems.INTERVAL
        # Coefficient matrices A0..Ap when a polynomial problem is
        # loaded; None for the ordinary linear ones.
        self.poly_matrices = None
        self._ratio = None
        self._centre = complex(0.0, 0.0)
        self._radius = 1.0
        self.bounds = None
        self.convergence = []
        self.diagnosis = None
        self._syncing = False
        self.solving = False
        self.worker: SolveWorker | None = None
        self.counter: CountWorker | None = None

        self.license_status = licensing.load()

        self._build_ui()
        self._build_menu()
        self._check_library()
        self.refresh_license()
        self.load_demo()

    # ---------------------------------------------------------------- UI ----
    def _build_ui(self):
        splitter = QSplitter(Qt.Horizontal)

        # ---- left: controls
        left = QWidget()
        lv = QVBoxLayout(left)

        src = QGroupBox("Matrix")
        sf = QVBoxLayout(src)
        # Every problem FEAST 4.0 ships, not just a couple of synthetic ones:
        # the 12 named problems its own Linux driver is meant to be run on,
        # plus the generated demos. Grouped, with the ones the GUI cannot solve
        # shown but disabled rather than quietly omitted -- a catalogue that
        # hides what it cannot do is a catalogue you cannot trust.
        self.demo_combo = QComboBox()
        self._populate_problems()
        self.demo_combo.currentIndexChanged.connect(self.load_demo)
        sf.addWidget(QLabel("Built-in problem:"))
        sf.addWidget(self.demo_combo)
        self.problem_note = QLabel("")
        self.problem_note.setWordWrap(True)
        self.problem_note.setStyleSheet("font-size: 11px; font-style: italic;")
        sf.addWidget(self.problem_note)
        openrow = QHBoxLayout()
        open_btn = QPushButton("Open matrix file...")
        open_btn.clicked.connect(self.open_file)
        openrow.addWidget(open_btn)
        gen_btn = QPushButton("Generate random...")
        gen_btn.setToolTip("Make a random test matrix of a size you choose.")
        gen_btn.clicked.connect(self.generate_matrix)
        openrow.addWidget(gen_btn)
        sf.addLayout(openrow)
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

        self.fit_btn = QPushButton("Fit view to results")
        self.fit_btn.setToolTip("Re-frame the plot around what was found.\n"
                                "Double-clicking the plot does the same.")
        self.fit_btn.clicked.connect(self.fit_view)
        itf.addRow(self.fit_btn)

        self.zoom_out_btn = QPushButton("Zoom out to full spectrum")
        self.zoom_out_btn.setToolTip("Solving zooms the plot to the interval; "
                                     "this returns to the whole spectral range.")
        self.zoom_out_btn.clicked.connect(self.zoom_full)
        self.zoom_out_btn.setEnabled(False)
        itf.addRow(self.zoom_out_btn)
        lv.addWidget(interval)

        params = QGroupBox("Parameters")
        pf = QFormLayout(params)
        # Disc controls. Shown only for a non-Hermitian problem, because an
        # interval is meaningless there and a disc is meaningless for a
        # Hermitian one -- offering both at once would invite a nonsense run.
        self.disc_box = QGroupBox("Search disc (complex plane)")
        df = QFormLayout(self.disc_box)
        self.emid_re = QDoubleSpinBox()
        self.emid_im = QDoubleSpinBox()
        self.radius = QDoubleSpinBox()
        for w in (self.emid_re, self.emid_im, self.radius):
            w.setDecimals(6)
            w.setRange(-1e12, 1e12)
        self.radius.setMinimum(1e-12)
        self.radius.setValue(1.0)
        df.addRow("Centre (real)", self.emid_re)
        df.addRow("Centre (imag)", self.emid_im)
        df.addRow("Radius", self.radius)
        self.disc_box.setVisible(False)
        lv.addWidget(self.disc_box)

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

        # The quadrature rule is a genuine algorithmic choice, not a tuning
        # knob: it changes where the integration points sit and therefore the
        # shape of the filter. Measured on the 200-point Laplacian it changes
        # the loop count from 9 (Gauss) to 12 (Trapezoidal) to 11 (Zolotarev).
        self.rule = QComboBox()
        for r in (contours.GAUSS, contours.TRAPEZOIDAL, contours.ZOLOTAREV):
            self.rule.addItem(contours.RULE_NAMES[r], r)
        self.rule.setToolTip(algorithms.QUADRATURE.summary)
        pf.addRow("Quadrature rule", self.rule)

        self.auto_m0 = QCheckBox("Retry automatically if M0 is too small")
        self.auto_m0.setChecked(True)
        pf.addRow(self.auto_m0)

        explain = QPushButton("What do these options do?")
        explain.clicked.connect(self.show_algorithm_help)
        pf.addRow(explain)
        lv.addWidget(params)

        # Actions live outside the scroll area: Solve is the primary action and
        # must never scroll out of view, which is what happened on a short
        # window before this.
        actions = QWidget()
        actions_lv = QVBoxLayout(actions)
        actions_lv.setContentsMargins(0, 6, 0, 0)

        self.solve_btn = QPushButton("Solve")
        self.solve_btn.setMinimumHeight(38)
        f = QFont(); f.setBold(True); self.solve_btn.setFont(f)
        self.solve_btn.clicked.connect(self.on_solve_button)
        actions_lv.addWidget(self.solve_btn)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        actions_lv.addWidget(self.progress)

        self.code_btn = QPushButton("Copy as code...")
        self.code_btn.setToolTip("Emit this exact problem as a runnable Python "
                                 "or C program.")
        self.code_btn.clicked.connect(self.show_code)
        actions_lv.addWidget(self.code_btn)

        self.export_btn = QPushButton("Export results...")
        self.export_btn.clicked.connect(self.export_csv)
        self.export_btn.setEnabled(False)
        actions_lv.addWidget(self.export_btn)

        lv.addStretch(1)

        left_scroll = QScrollArea()
        left_scroll.setWidget(left)
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QScrollArea.NoFrame)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        left_column = QWidget()
        col = QVBoxLayout(left_column)
        col.setContentsMargins(0, 0, 0, 0)
        col.addWidget(left_scroll, stretch=1)
        col.addWidget(actions)              # pinned, always reachable
        left_column.setMinimumWidth(300)
        left_column.setMaximumWidth(348)    # room for the scrollbar
        splitter.addWidget(left_column)

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

        self.plot.setTitle("press Solve to find eigenvalues in the shaded band")
        # Double-click anywhere on either plot re-fits it, so getting lost while
        # panning is one click to undo rather than a hunt for the "A".
        self.plot.scene().sigMouseClicked.connect(self._plot_clicked)

        self.conv_plot = pg.PlotWidget()
        self.conv_plot.setBackground(None)
        self.conv_plot.setLabel("bottom", "refinement loop")
        self.conv_plot.setLabel("left", "error")
        self.conv_plot.setLogMode(y=True)      # errors span many decades
        self.conv_plot.showGrid(x=True, y=True, alpha=0.25)
        self.conv_plot.addLegend(offset=(-10, 10))

        # The matrix, the filter and the eigenvectors were all things the app
        # had access to and never showed. The filter in particular is the
        # object FEAST's own documentation is about, and the library ships a
        # routine (dfeast_rational) whose only purpose is to let you plot it.
        self.matrix_view = MatrixView()
        self.filter_view = FilterView()
        self.accuracy_view = SpectrumView()
        self.vector_view = EigenvectorView()
        self.accuracy_view.picked.connect(self._show_eigenvector)

        # One tab, two plots: a real line for an interval search and an Argand
        # plane for a disc search. Swapped by problem type rather than shown
        # side by side, since only one is ever meaningful.
        self.complex_view = ComplexSpectrumView()
        self.complex_view.picked.connect(self._show_eigenvector)
        self.spectrum_stack = QStackedWidget()
        self.spectrum_stack.addWidget(self.plot)
        self.spectrum_stack.addWidget(self.complex_view)

        self.tabs = QTabWidget()
        self.tabs.addTab(self.matrix_view, "Matrix")
        self.tabs.addTab(self.spectrum_stack, "Spectrum")
        self.tabs.addTab(self.filter_view, "Filter && contour")
        self.tabs.addTab(self.accuracy_view, "Accuracy")
        self.tabs.addTab(self.vector_view, "Eigenvector")
        self.tabs.addTab(self.conv_plot, "Convergence")
        self.tabs.currentChanged.connect(self._tab_changed)
        self.rsplit = QSplitter(Qt.Vertical)
        self.rsplit.setChildrenCollapsible(True)
        self.rsplit.addWidget(self.tabs)

        self.empty_label = QLabel()
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setWordWrap(True)
        self.empty_label.setStyleSheet("color: palette(text); font-size: 13px;")

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["#", "eigenvalue", "residual"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        # We render our own "#" column, so Qt's row numbers would be a duplicate.
        self.table.verticalHeader().setVisible(False)
        self.results_stack = QStackedWidget()
        self.results_stack.addWidget(self.empty_label)   # 0
        self.results_stack.addWidget(self.table)         # 1
        self.rsplit.addWidget(self.results_stack)
        self._show_placeholder("Choose a search interval, then press Solve.\n\n"
                               "The shaded band on the plot is the interval; "
                               "drag it to move it.")

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(130)
        self.log.setFont(QFont("Consolas" if sys.platform == "win32" else "Menlo", 9))
        self.rsplit.addWidget(self.log)
        # Growth goes to the plot: the table scrolls, so showing 40 rows instead
        # of 20 helps far less than a bigger spectrum does.
        self.rsplit.setStretchFactor(0, 3)
        self.rsplit.setStretchFactor(1, 2)
        self.rsplit.setStretchFactor(2, 0)
        # Stretch factors only govern *extra* space; without explicit starting
        # sizes the panes open at their size hints and the log ends up larger
        # than the results table.
        self.rsplit.setSizes([440, 300, 110])
        self.results_stack.setMinimumHeight(120)
        rv.addWidget(self.rsplit)

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
        a = QAction("&Licence...", self)
        a.triggered.connect(self.show_license)
        h.addAction(a)
        a = QAction("&About", self)
        a.triggered.connect(self.about); h.addAction(a)

    # ------------------------------------------------------------ actions ----
    def _show_placeholder(self, text: str):
        self.empty_label.setText(text)
        self.results_stack.setCurrentIndex(0)

    def _show_results_table(self):
        self.results_stack.setCurrentIndex(1)

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

    # -- plot navigation ---------------------------------------------------
    def _plot_clicked(self, ev):
        """Double-click re-fits the plot.

        Panning off the data and not knowing how to get back is the single
        easiest way to lose a result. pyqtgraph's own escape hatch is a tiny
        'A' in the corner, which nobody finds without being told.
        """
        try:
            if ev.double():
                self.fit_view()
        except Exception:
            pass

    @Slot()
    def fit_view(self):
        """Frame whatever is worth looking at on the current tab."""
        if self.tabs.currentIndex() == 1:
            self.conv_plot.enableAutoRange()
            self.conv_plot.autoRange()
            return
        r = self.result
        if r is not None and r.n_found:
            lo, hi = float(min(r.eigenvalues)), float(max(r.eigenvalues))
            span = hi - lo
            pad = 0.08 * span if span > 0 else max(abs(hi) * 1e-6, 1e-9)
            self.plot.setXRange(lo - pad, hi + pad)
            self.plot.setYRange(0, r.n_found + 1)
        elif self.bounds is not None:
            lo, hi = self.bounds
            pad = 0.02 * (hi - lo) or 1e-9
            self.plot.setXRange(lo - pad, hi + pad)
        else:
            self.plot.enableAutoRange()
            self.plot.autoRange()

    def _apply_pan_limits(self):
        """Stop the view wandering somewhere with nothing in it.

        Without limits a scroll-wheel zoom can leave the data thousands of units
        away with no cue about which direction to go back.
        """
        if self.bounds is None:
            return
        lo, hi = self.bounds
        span = (hi - lo) or 1.0
        self.plot.setLimits(xMin=lo - span, xMax=hi + span,
                            minXRange=span * 1e-9, maxXRange=span * 4)

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
        self._apply_pan_limits()
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
    def _populate_problems(self):
        """Fill the built-in list: FEAST's own problems, then generated ones."""
        from PySide6.QtGui import QStandardItem

        combo = self.demo_combo
        combo.blockSignals(True)
        combo.clear()

        def header(text):
            combo.addItem(f"--- {text} ---")
            item = combo.model().item(combo.count() - 1)
            item.setEnabled(False)
            f = item.font()
            f.setBold(True)
            item.setFont(f)

        for group, plist in problems.groups().items():
            usable = [p for p in plist if problems.available(p)]
            if not usable:
                continue
            header(group)
            for p in usable:
                # Both search geometries work now. The polynomial problem is
                # the only one still out of reach: it needs three matrices and
                # a routine family feastpy has no entry point for.
                ok = p.solver is not None
                label = f"{p.title}  (n={p.n:,})"
                combo.addItem(label, ("problem", p.id))
                if not ok:
                    it = combo.model().item(combo.count() - 1)
                    it.setEnabled(False)
                    it.setToolTip("The matrix data for this problem is not "
                                  "present in this build.")

        header("Generated")
        for name in matrixio.DEMOS:
            combo.addItem(name, ("demo", name))

        # Open on the 1-D Laplacian, not on whatever happens to be first.
        # FEAST's own hello-world is a 4x4 with two eigenvalues at the same
        # place -- ideal for checking the arithmetic by hand, and a poor first
        # impression of a spectrum plot.
        default = next(iter(matrixio.DEMOS), None)
        target = 0
        for i in range(combo.count()):
            if not combo.model().item(i).isEnabled():
                continue
            data = combo.itemData(i)
            if isinstance(data, tuple) and data == ("demo", default):
                target = i
                break
            if not target:
                target = i          # fall back to the first usable row
        combo.setCurrentIndex(target)
        combo.blockSignals(False)

    def load_demo(self):
        data = self.demo_combo.currentData()
        if isinstance(data, tuple) and data[0] == "problem":
            self._load_catalogue_problem(problems.get(data[1]))
            return
        name = data[1] if isinstance(data, tuple) else self.demo_combo.currentText()
        if name not in matrixio.DEMOS:
            return
        self.problem_note.setText("")
        self._uplo = "F"
        self.poly_matrices = None
        self._ratio = None
        self._set_geometry(problems.INTERVAL)
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
        self._refresh_matrix_view(name)
        self._log(f"loaded demo: {name}")

    def _load_catalogue_problem(self, p):
        """Load one of the problems FEAST itself ships, with its own settings."""
        self._log(f"loading {p.title} ...")
        QApplication.processEvents()          # a 49k-row matrix takes a moment
        try:
            A, B = problems.load(p)
        except Exception as exc:
            QMessageBox.warning(self, "Could not load", str(exc))
            return

        if p.polynomial:
            # A is the list of coefficient matrices. Show A0 in the Matrix tab
            # -- it is the one with the problem's structure -- and keep the set
            # for the solve.
            self.poly_matrices = A
            self.matrix, self.b_matrix = A[0], None
        else:
            self.poly_matrices = None
            self.matrix, self.b_matrix = A, None
        self.matrix_path, self.b_path = p.a_file, p.b_file
        self.clear_b_btn.setEnabled(False)
        self.b_label.setText("no B - standard problem A x = λ x")
        if B is not None:
            keep = p.b_file
            self._set_b(B, "shipped with this problem")
            self.b_path = keep

        # The .in file's UPLO describes the file; what matters is the array we
        # actually hold, which differs for the one problem carrying a Matrix
        # Market banner (scipy mirrors it).
        self._uplo = ("F" if p.polynomial
                      else problems.effective_uplo(A, p.uplo))
        if p.geometry == problems.DISC:
            self._set_geometry(problems.DISC, p.emid, p.radius)
        else:
            self._set_geometry(problems.INTERVAL)
            self.emin.setValue(p.emin)
            self.emax.setValue(p.emax)
        self.m0.setValue(min(p.m0, (A[0] if p.polynomial else A).shape[0]))
        # Some problems only work at settings their own example uses -- a very
        # flat contour, a looser tolerance. Apply them rather than letting the
        # defaults quietly find nothing.
        self._ratio = p.ratio
        if p.contour_points:
            self.contour.setValue(p.contour_points)
        if p.tol_exponent:
            self.tol.setValue(p.tol_exponent)
        if p.max_loops:
            self.loops.setValue(p.max_loops)
        self.matrix_label.setText(
            matrixio.describe(A[0] if p.polynomial else A)
            + (f"  (+{len(A) - 1} more coefficient matrices)"
               if p.polynomial else ""))

        note = p.about
        if p.note:
            note += "  " + p.note
        if p.caveat:
            note = "⚠ " + p.caveat + "  " + note
        self.problem_note.setText(note)

        self._update_spectrum_view()
        self._refresh_matrix_view(p.title)
        if p.polynomial:
            self._log(f"loaded {p.title}: degree {len(A) - 1} polynomial, "
                      f"n={A[0].shape[0]}, {len(A)} coefficient matrices, "
                      f"search {p.search_text}, M0={p.m0}")
        else:
            self._log(f"loaded {p.title}: n={A.shape[0]}, search {p.search_text}, "
                      f"M0={p.m0}, uplo={self._uplo}")
        if p.caveat:
            self._log("note: " + p.caveat)

    def show_algorithm_help(self):
        """Every algorithmic option FEAST offers, explained in plain English.

        The guide documents the parameters but not which to reach for, and
        several of the most useful ones -- the iterative preconditioner, for
        one -- are not documented at all.
        """
        dlg = QDialog(self)
        dlg.setWindowTitle("FEAST algorithm options")
        dlg.resize(760, 620)
        lv = QVBoxLayout(dlg)
        body = QTextEdit()
        body.setReadOnly(True)

        herm = True
        html = ["<h2>Algorithm options</h2>",
                "<p>FEAST is a contour-integration solver. These are the "
                "choices that change what it does, not just how long it "
                "takes. Values in <b>bold</b> are what FEAST uses if you do "
                "not choose.</p>"]
        for tier in algorithms.tiers():
            opts = [o for o in algorithms.for_problem(herm, tier)]
            if not opts:
                continue
            html.append(f"<h3>{algorithms.TIER_LABELS[tier]}</h3>")
            for o in opts:
                html.append(f"<p><b>{o.label}</b> "
                            f"<code>{o.key}</code><br>"
                            f"{o.detail.replace(chr(10) + chr(10), '<br><br>')}")
                if o.choices:
                    html.append("<ul>" + "".join(
                        f"<li><b>{c.label}</b> — {c.detail}"
                        + (f"<br><i>Caveat: {c.caveat}</i>" if c.caveat else "")
                        + "</li>" for c in o.choices) + "</ul>")
                if o.default_text:
                    html.append(f"<br><b>Default:</b> {o.default_text}")
                if o.caveat:
                    html.append(f"<br><i>Caveat: {o.caveat}</i>")
                html.append("</p>")
        body.setHtml("".join(html))
        lv.addWidget(body)
        close = QPushButton("Close")
        close.clicked.connect(dlg.accept)
        lv.addWidget(close)
        dlg.exec()

    def _update_views(self, r):
        """Feed a finished solve to the new views. Never fatal: a plot that
        cannot draw must not lose the user their result."""
        emin, emax = self.emin.value(), self.emax.value()
        disc = (self._geometry == problems.DISC)

        rejected = None
        if r.all_eigenvalues is not None and r.n_found < len(r.all_eigenvalues):
            rejected = r.all_eigenvalues[r.n_found:]
            keep = np.isfinite(np.abs(rejected)) & (np.abs(rejected) < 1e30)
            rejected = rejected[keep]

        if disc:
            try:
                self.complex_view.show_search(self._centre, self._radius,
                                              r.eigenvalues, rejected)
            except Exception as exc:
                self._log(f"complex spectrum view unavailable: {exc}")
            try:
                self.filter_view.show_disc(self._centre, self._radius,
                                           r.eigenvalues)
            except Exception as exc:
                self._log(f"filter view unavailable: {exc}")
            try:
                self.vector_view.set_result(r.eigenvalues, r.eigenvectors)
            except Exception as exc:
                self._log(f"eigenvector view unavailable: {exc}")
            try:
                # Distance from the disc centre is the honest 1-D stand-in for
                # position when the eigenvalues are spread over a plane.
                d = np.abs(np.asarray(r.eigenvalues, dtype=complex)
                           - self._centre)
                tol = 10.0 ** (-self.tol.value())
                self.accuracy_view.show_result(d, r.residuals, 0.0,
                                               self._radius, tol=tol)
                self.accuracy_view.plot.setLabel("bottom",
                                                 "distance from disc centre")
            except Exception as exc:
                self._log(f"accuracy view unavailable: {exc}")
            return

        self.accuracy_view.plot.setLabel("bottom", "eigenvalue")
        try:
            # The subspace slots FEAST examined and rejected as outside the
            # interval. Showing them is how "is M0 big enough" stops being
            # folklore: if none were rejected, the subspace was full to the brim.
            rej = rejected
            rej_res = (r.all_residuals[r.n_found:][:len(rej)]
                       if rej is not None else None)
            tol = 10.0 ** (-self.tol.value()) if hasattr(self, "tol") else None
            self.accuracy_view.show_result(np.real(r.eigenvalues), r.residuals,
                                           emin, emax, rej, rej_res, tol)
        except Exception as exc:
            self._log(f"accuracy view unavailable: {exc}")
        try:
            self.vector_view.set_result(r.eigenvalues, r.eigenvectors)
        except Exception as exc:
            self._log(f"eigenvector view unavailable: {exc}")
        try:
            self.filter_view.show_interval(emin, emax, np.real(r.eigenvalues))
        except Exception as exc:
            self._log(f"filter view unavailable: {exc}")

    def _tab_changed(self, _index: int):
        """The filter depends only on the interval, so it is worth drawing
        before any solve -- that is the point of it. Refresh on reveal."""
        if self.tabs.currentWidget() is self.filter_view:
            try:
                vals = np.real(self.result.eigenvalues) if self.result else None
                self.filter_view.show_interval(self.emin.value(),
                                               self.emax.value(), vals)
            except Exception as exc:
                self._log(f"filter view unavailable: {exc}")

    def _show_eigenvector(self, idx: int):
        self.vector_view.show_index(idx)
        self.tabs.setCurrentWidget(self.vector_view)

    def _set_geometry(self, geometry: str, centre=None, radius=None):
        """Put the whole window into interval mode or disc mode."""
        self._geometry = geometry
        disc = (geometry == problems.DISC)
        if centre is not None:
            self._centre = complex(centre)
            self.emid_re.setValue(self._centre.real)
            self.emid_im.setValue(self._centre.imag)
        if radius is not None:
            self._radius = float(radius)
            self.radius.setValue(self._radius)

        # FEAST's own default point count differs by geometry: 8 on a
        # Hermitian half-contour, 16 on a full one, because a closed contour in
        # the plane has no conjugate symmetry to exploit. Carrying 8 into a
        # disc search starts it under-resourced and it often fails to converge.
        if disc and self.contour.value() == 8:
            self.contour.setValue(16)
        elif not disc and self.contour.value() == 16:
            self.contour.setValue(8)

        self.disc_box.setVisible(disc)
        # The interval controls drive a solve that cannot run in disc mode, so
        # hide them rather than leave them live and ignored.
        for w in (self.emin, self.emax, self.full_range_btn, self.count_btn,
                  self.fit_btn, self.zoom_out_btn):
            w.setEnabled(not disc)
        self.spectrum_stack.setCurrentWidget(
            self.complex_view if disc else self.plot)
        if disc:
            self.complex_view.show_search(self._centre, self._radius)

    def _refresh_matrix_view(self, title: str):
        try:
            self.matrix_view.show_matrix(self.matrix, self.b_matrix,
                                         getattr(self, "_uplo", "F"), title)
        except Exception as exc:                      # never block a load
            self._log(f"matrix view unavailable: {exc}")

    def _clear_demo_selection(self):
        """Stop the dropdown claiming a demo is loaded when it is not.

        Opening a file or generating a matrix leaves the combo showing whatever
        demo was chosen last, which is simply untrue.
        """
        self.demo_combo.blockSignals(True)
        self.demo_combo.setCurrentIndex(-1)
        self.demo_combo.blockSignals(False)

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
    def generate_matrix(self):
        dlg = GenerateDialog(self)
        if dlg.exec() != QDialog.Accepted or not dlg.result_matrices:
            return
        A, B, label = dlg.result_matrices
        if self._license_blocks(A):
            return
        self.matrix = A
        self.matrix_path = None
        self.b_path = None
        self.b_matrix = None
        self._clear_demo_selection()
        self.clear_b_btn.setEnabled(False)
        self.b_label.setText("no B - standard problem A x = λ x")
        self.matrix_label.setText(f"{matrixio.describe(A)}  ({label})")
        if B is not None:
            self._set_b(B, "generated")
        self._update_spectrum_view()
        self._log(f"generated {label}: {matrixio.describe(A)}")
        # A fresh random spectrum makes the previous interval meaningless.
        self.use_full_range()

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

        # Not a reason to refuse. A non-Hermitian matrix has a complex spectrum
        # and therefore no interval to search, but the app has had a disc mode
        # all along -- it is how the built-in system3 is solved. Turning a
        # user's own matrix away while solving a demo of the same kind was a
        # gap in the UI, not a limit of the library.
        #
        # `herm` alone decides, not `sym or herm`: a complex symmetric matrix
        # (A == A.T, A != A.H) has a complex spectrum too, and treating it as
        # Hermitian returns real numbers for it.
        _, herm = matrixio.check_symmetry(M)

        if self._license_blocks(M):
            return
        self.matrix = M
        self.matrix_path = path
        self.b_matrix = None
        self.b_path = None
        self._clear_demo_selection()
        self.clear_b_btn.setEnabled(False)
        self.b_label.setText("no B - standard problem A x = λ x")
        # Read the storage off the data rather than assuming. FEAST's own
        # sample files are a mix: some ship both triangles, some only the
        # lower one, and only bcsstk11 carries a banner saying so.
        self.poly_matrices = None
        # A non-Hermitian matrix must be stored in full: the general routines
        # read both triangles, and handing them half a matrix solves a
        # different problem.
        self._uplo = ("F" if not herm
                      else problems.effective_uplo(M, "F") if sp.issparse(M)
                      else "F")

        if herm:
            self._set_geometry(problems.INTERVAL)
        else:
            # Put the contour somewhere the spectrum actually is. Gershgorin
            # costs one pass over the nonzeros and beats opening in disc mode
            # with a stale circle from whatever was loaded before.
            try:
                centre, radius = feastpy.spectral_disc(M)
            except Exception:
                centre, radius = complex(0.0, 0.0), 1.0
            self._set_geometry(problems.DISC, centre, radius)

        self.matrix_label.setText(matrixio.describe(M))
        self._update_spectrum_view()
        self._refresh_matrix_view(Path(path).name)
        self._log(f"loaded {Path(path).name}: {matrixio.describe(M)} "
                  f"(stored as uplo='{self._uplo}')")
        if not herm:
            self._log("  not Hermitian - its eigenvalues are complex, so the "
                      "search is a disc in the plane rather than an interval; "
                      f"opened on radius {self._radius:.4g} about "
                      f"{self._centre:.4g}")

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
            m0=self.m0.value(),
            contour_points=self.contour.value(),
            tol_exponent=self.tol.value(),
            max_loops=self.loops.value(),
            # The built-in problems declare how their file is stored; a matrix
            # opened from disk is assumed full. Getting this wrong silently
            # discards half the matrix, so it is threaded explicitly.
            uplo=getattr(self, "_uplo", "F"),
        )
        if self.poly_matrices is not None:
            # eig_polynomial has no 'rule' or 'uplo="U"' path and takes the
            # matrices positionally through the runner.
            params.pop("uplo", None)
            params["uplo"] = "F"
            self._centre = complex(self.emid_re.value(), self.emid_im.value())
            self._radius = self.radius.value()
            params["center"] = self._centre
            params["radius"] = self._radius
            if self._ratio:
                params["ratio"] = self._ratio
        elif self._geometry == problems.DISC:
            self._centre = complex(self.emid_re.value(), self.emid_im.value())
            self._radius = self.radius.value()
            params["center"] = self._centre
            params["radius"] = self._radius
        else:
            params["emin"] = self.emin.value()
            params["emax"] = self.emax.value()
            # fpm(16) is only wired through the interval routines so far.
            params["rule"] = self.rule.currentData()
        if not self.solving:          # a fresh solve, not an auto-retry
            self.convergence = []
            self.conv_plot.clear()
        where = (f"disc centre {self._centre.real:g}{self._centre.imag:+g}i "
                 f"radius {self._radius:g}" if self._geometry == problems.DISC
                 else f"[{params['emin']:g}, {params['emax']:g}]")
        self._log(f"solving on {where} with M0={params['m0']}...")
        self._set_solving(True)
        self.statusBar().showMessage("solving...")

        # A polynomial problem is defined by all its coefficient matrices, not
        # by A0 alone -- self.matrix holds A0 only so the Matrix tab has
        # something to show.
        operand = self.poly_matrices if self.poly_matrices is not None else self.matrix
        self.worker = SolveWorker(operand, self.b_matrix, params)
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
        if getattr(r, "routine", ""):
            self._log(f"  routine: {r.routine}")
        self._update_views(r)
        self.statusBar().showMessage(
            f"{r.n_found} eigenvalues  |  {secs:.2f}s  |  {r.message}")

        if r.n_found:
            self._show_results_table()
        else:
            self._show_placeholder(
                f"No eigenvalues in [{self.emin.value():g}, {self.emax.value():g}].\n\n"
                'Try "Use whole spectrum", or "How many are in here?" to find '
                "where they are.")
        self.table.setRowCount(r.n_found)
        # A disc search returns complex eigenvalues; "%.12g" on a complex
        # number raises, so format the two parts explicitly.
        def _fmt(v):
            if np.iscomplexobj(r.eigenvalues):
                return f"{v.real:.12g} {'+' if v.imag >= 0 else '-'} {abs(v.imag):.12g}i"
            return f"{v:.12g}"

        for i in range(r.n_found):
            for col, text in ((0, str(i + 1)),
                              (1, _fmt(r.eigenvalues[i])),
                              (2, f"{r.residuals[i]:.3e}")):
                item = QTableWidgetItem(text)
                if col:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(i, col, item)

        self.plot.clear()
        self.plot.addItem(self.region)      # clear() drops it otherwise
        if r.n_found and not np.iscomplexobj(r.eigenvalues):
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
            self.plot.setTitle(None)
        else:
            # Nothing found: show WHERE we looked, otherwise the axis still
            # frames the previous run and the interval is off-screen entirely.
            lo, hi = self.emin.value(), self.emax.value()
            pad = 0.5 * (hi - lo) or 1e-9
            self.plot.setXRange(lo - pad, hi + pad)
            self.plot.setTitle("no eigenvalues in this interval")
            self.zoom_out_btn.setEnabled(self.bounds is not None)
        self.export_btn.setEnabled(r.n_found > 0)

        self.diagnosis = self._diagnose(r)
        for sug in self.diagnosis.suggestions:
            self._log(f"  hint: {sug.text}")
        if r.info != 0:
            self._offer_fix(self.diagnosis)

    def _diagnose(self, r):
        # The advice has to describe the region actually searched. Passing the
        # interval unconditionally meant a disc search was told to "widen the
        # interval" -- a control that is hidden in disc mode -- while the fix
        # it needed, a larger radius, was never offered.
        if self._geometry == problems.DISC:
            region = {"center": self._centre, "radius": self._radius}
            # `bounds` is read as (centre, radius) in disc mode, so handing it
            # self.bounds -- an interval (lo, hi) -- would render a disc
            # "about 0.18 of radius 1.0" out of two unrelated numbers. Compute
            # the real bounding disc, or say nothing.
            try:
                bounds = feastpy.spectral_disc(self.matrix, self.b_matrix)
            except Exception:
                bounds = None
        else:
            region = {"emin": self.emin.value(), "emax": self.emax.value()}
            bounds = self.bounds
        return diagnostics.diagnose(
            r, n=int(self.matrix.shape[0]), m0=self.m0.value(),
            contour_points=self.contour.value(), tol_exponent=self.tol.value(),
            max_loops=self.loops.value(), bounds=bounds, **region)

    def apply_suggestion(self, sug) -> bool:
        """Apply a suggested parameter change. Returns True if anything changed."""
        if not sug.actionable:
            return False
        if sug.param == "m0":
            self.m0.setValue(int(sug.value))
        elif sug.param == "max_loops":
            self.loops.setValue(int(sug.value))
        elif sug.param == "contour_points":
            self.contour.setValue(int(sug.value))
        elif sug.param == "tol_exponent":
            self.tol.setValue(int(sug.value))
        elif sug.param == "interval":
            lo, hi = sug.value
            self.emin.setValue(float(lo))
            self.emax.setValue(float(hi))
        else:
            return False
        self._log(f"  applied: {sug.text}")
        return True

    def _offer_fix(self, diag):
        """Show what went wrong and offer to fix it in one click.

        A status code the user has to look up is a dead end; the fix is usually
        a single parameter, so make that the default button.
        """
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning if diag.info > 0 else QMessageBox.Critical)
        box.setWindowTitle(APP_NAME)
        box.setText(diag.headline)
        body = diag.detail
        others = [s for s in diag.suggestions if not s.actionable]
        if others:
            body += "\n\n" + "\n".join("- " + s.text for s in others)
        box.setInformativeText(body)

        fixes = [s for s in diag.suggestions if s.actionable]
        buttons = []
        for sug in fixes[:2]:
            btn = box.addButton(sug.text, QMessageBox.ActionRole)
            buttons.append((btn, sug))
        close = box.addButton("Close", QMessageBox.RejectRole)
        box.setDefaultButton(buttons[0][0] if buttons else close)
        box.exec()

        for btn, sug in buttons:
            if box.clickedButton() is btn:
                if self.apply_suggestion(sug):
                    self.solve()
                return

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
    def show_license(self):
        LicenseDialog(self).exec()

    def refresh_license(self):
        self.license_status = licensing.load()
        # Only say "free version" when this build actually enforces something.
        if self.license_status.licensed or not licensing.ENABLED:
            self.setWindowTitle(APP_NAME)
        else:
            self.setWindowTitle(f"{APP_NAME}  -  free version")

    def _license_blocks(self, M) -> bool:
        """Warn and refuse if this matrix is past the free-tier ceiling.

        Checked when the matrix is loaded rather than when Solve is pressed, so
        nobody configures a run and only then discovers the wall.
        """
        if self.license_status.licensed or M is None:
            return False
        sparse = sp.issparse(M)
        why = licensing.check_size(int(M.shape[0]), sparse,
                                   int(M.nnz) if sparse else 0)
        if not why:
            return False
        QMessageBox.information(
            self, APP_NAME,
            why + "\n\nEverything else is unrestricted, and smaller problems "
            "work normally. Help -> Licence has the machine id to buy one.")
        return True

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


def selftest() -> int:
    """Solve a problem with a known answer and report. No window.

    This is how a packaged binary gets checked: it exercises the bundled
    libfeast, the child-process runner and the sample data, without needing a
    display or a person to click anything.
    """
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    # A windowed build on Windows has no console attached, so print() goes
    # nowhere when it is launched from a terminal. Mirror everything to a file
    # so a packaged binary can still be checked.
    report_path = os.environ.get("FEAST_SELFTEST_OUT", "feast-selftest.txt")
    lines = []

    def say(msg):
        print(msg)
        lines.append(str(msg))

    def flush():
        try:
            Path(report_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError:
            pass

    app = QApplication(sys.argv)
    w = MainWindow()

    say(f"platform: {sys.platform} frozen={getattr(sys, 'frozen', False)}")
    say(f"library : {feastpy.load()._name}")
    say(f"samples : {matrixio.DATA_DIR}")
    # The built-in catalogue resolves its matrices by path, and a frozen app
    # has no source tree -- so this is precisely the thing that breaks on
    # packaging while every other check still passes. Count what actually
    # loads, and name what is missing rather than letting it vanish quietly.
    _avail = [p for p in problems.ALL if problems.available(p)]
    _missing = [p.id for p in problems.ALL if not problems.available(p)]
    say(f"problems: {len(_avail)} of {len(problems.ALL)} built-in problems found"
        + (f" (absent: {', '.join(_missing)})" if _missing else ""))

    # The Filter and contour views go through feastpy.raw, which parses FEAST's
    # C headers for its signatures. A packaged build that omits those headers
    # solves perfectly and draws an empty Filter tab -- every other check here
    # passes, because solver.py binds the library directly. So exercise the raw
    # path explicitly: it is the only thing that catches a missing header.
    _filter_ok = False
    try:
        from feastpy import contours
        _E, _f = contours.filter_curve(0.0, 1.0, points=8)
        _Z, _W = contours.interval_contour(0.0, 1.0, points=8)
        # The filter overshoots 1 slightly near the interval edges -- that
        # ripple is inherent to a rational approximation, not an error.
        _peak = abs(_f).max()
        _filter_ok = (len(_Z) == 8 and 0.9 < _peak < 1.3
                      and abs(_f[0]) < 1e-3)
        say(f"filter  : {len(raw.signatures())} routine signatures, "
            f"contour {len(_Z)} nodes, filter peak {abs(_f).max():.4f}")
    except Exception as exc:
        say(f"filter  : UNAVAILABLE -- {type(exc).__name__}: {exc}")

    exact = [2 - 2 * np.cos((k + 1) * np.pi / 201) for k in range(9)]
    ok = {"solved": False}

    def done(r, secs):
        err = (max(abs(a - b) for a, b in zip(sorted(r.eigenvalues), exact))
               if r.n_found == 9 else float("inf"))
        say(f"solved  : info={r.info} found={r.n_found} in {secs:.2f}s")
        say(f"accuracy: max error vs analytic = {err:.2e}")
        ok["solved"] = r.info == 0 and r.n_found == 9 and err < 1e-10
        app.quit()

    def failed(msg):
        say(f"FAILED  : {msg}")
        app.quit()

    w.emin.setValue(0.0)
    w.emax.setValue(0.02)
    w.m0.setValue(20)
    w.worker = SolveWorker(w.matrix, None, dict(
        emin=0.0, emax=0.02, m0=20, contour_points=8,
        tol_exponent=12, max_loops=20))
    w.worker.finished_ok.connect(done)
    w.worker.failed.connect(failed)
    w.worker.start()
    QTimer.singleShot(120_000, app.quit)
    app.exec()

    # A bundle that solves but ships none of its built-in problems is a
    # broken bundle, so it fails the self-test rather than passing quietly.
    passed = ok["solved"] and len(_avail) >= 10 and _filter_ok
    say("SELFTEST PASS" if passed else "SELFTEST FAIL")
    flush()
    return 0 if passed else 1


def main():
    # Solves run in a child process. In a bundled app sys.executable is this
    # program, so the child would relaunch the GUI; the flag routes it to the
    # worker instead. Harmless when running from source, where the child is
    # started as `python -m feastpy._solve_child`.
    import os
    if getattr(sys, "frozen", False) and os.environ.get(runner.CHILD_ENV_FLAG):
        from feastpy import _solve_child
        return _solve_child.main(sys.argv[1:])

    if "--selftest" in sys.argv:
        return selftest()

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
