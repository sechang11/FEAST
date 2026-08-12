"""Plot views for the FEAST desktop app.

Each view is a self-contained widget that knows how to draw one thing and
nothing else, so the main window stays a place that wires things together
rather than a place that draws.

The views exist because of a specific criticism: the app showed numbers but not
meaning. It never showed the matrix, its main plot had an axis ("index") that
was just a row number dressed up as data, and it showed none of the objects the
FEAST documentation is actually about -- the rational filter and the contour.
"""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QHBoxLayout,
                               QLabel, QSplitter, QVBoxLayout, QWidget)

import scipy.sparse as sp

from feastpy import contours as C

# Muted, colour-blind-safe. Blue = accepted, orange = rejected, grey = context.
ACCEPT = "#3b78c3"
REJECT = "#d1893b"
MUTED = "#8a8a8a"
BAND = (90, 140, 200, 45)


def _plot(bottom: str, left: str) -> pg.PlotWidget:
    w = pg.PlotWidget()
    w.setBackground(None)
    w.showGrid(x=True, y=True, alpha=0.25)
    w.setLabel("bottom", bottom)
    w.setLabel("left", left)
    return w


class FilterView(QWidget):
    """The rational filter, and the contour that produces it.

    This is the picture the FEAST papers are about. The library ships routines
    whose only purpose is to produce it -- dfeast_rational computes nothing you
    can solve with -- so drawing it is using FEAST as intended rather than
    inventing a visualisation.

    It answers, in one look, the questions users otherwise learn by suffering:
    why the subspace must be larger than the answer (the filter does not reach
    zero, so outside eigenvalues leak in), what the contour point count buys,
    and why an interval edge must never be placed on an eigenvalue -- the
    filter is exactly 0.5 there, so such an eigenvalue is half in and half out.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setLayout(QVBoxLayout())
        self.layout().setContentsMargins(4, 4, 4, 4)

        row = QHBoxLayout()
        self.rule = QComboBox()
        for r in (C.GAUSS, C.TRAPEZOIDAL, C.ZOLOTAREV):
            self.rule.addItem(C.RULE_NAMES[r], r)
        self.points = QComboBox()
        for p in (2, 4, 6, 8, 12, 16, 24, 32, 48):
            self.points.addItem(str(p), p)
        self.points.setCurrentText("8")
        self.logy = QCheckBox("log scale")
        self.logy.setChecked(True)
        for w, lab in ((self.rule, "Quadrature rule"), (self.points, "Contour points")):
            row.addWidget(QLabel(lab + ":"))
            row.addWidget(w)
        row.addWidget(self.logy)
        row.addStretch(1)
        self.layout().addLayout(row)

        split = QSplitter(Qt.Horizontal)
        self.curve_plot = _plot("eigenvalue", "|filter|")
        self.contour_plot = _plot("real", "imaginary")
        self.contour_plot.setAspectLocked(True)
        split.addWidget(self.curve_plot)
        split.addWidget(self.contour_plot)
        split.setSizes([600, 400])
        self.layout().addWidget(split, 1)

        self.caption = QLabel("")
        self.caption.setWordWrap(True)
        self.caption.setStyleSheet(f"color: {MUTED};")
        self.layout().addWidget(self.caption)

        self._state = None
        for w in (self.rule, self.points):
            w.currentIndexChanged.connect(self._redraw)
        self.logy.toggled.connect(self._redraw)

    # -- public ------------------------------------------------------------
    def show_interval(self, emin: float, emax: float, eigenvalues=None):
        self._state = ("interval", float(emin), float(emax),
                       np.asarray(eigenvalues) if eigenvalues is not None else None)
        self._redraw()

    def show_disc(self, center: complex, radius: float, eigenvalues=None):
        self._state = ("disc", complex(center), float(radius),
                       np.asarray(eigenvalues) if eigenvalues is not None else None)
        self._redraw()

    # -- drawing -----------------------------------------------------------
    def _redraw(self):
        if self._state is None:
            return
        rule = self.rule.currentData()
        want = self.points.currentData()
        kind = self._state[0]
        full = (kind == "disc")

        # Zolotarev exists only for a Hermitian half-contour. Rather than let
        # FEAST report a rule it did not use, disable it and say why.
        zolo_ok = not full
        model = self.rule.model()
        model.item(2).setEnabled(zolo_ok)
        if not zolo_ok and rule == C.ZOLOTAREV:
            self.rule.setCurrentIndex(0)
            return
        points = C.nearest_legal(want, rule, full)

        self.curve_plot.clear()
        self.contour_plot.clear()
        self.curve_plot.setLogMode(y=self.logy.isChecked())

        if kind == "interval":
            self._draw_interval(rule, points)
        else:
            self._draw_disc(rule, points)

    def _draw_interval(self, rule, points):
        _, emin, emax, eig = self._state
        E, f = C.filter_curve(emin, emax, points, rule)
        y = np.abs(f)
        # A log axis cannot show zero; clamp to something below the smallest
        # meaningful value rather than dropping the points silently.
        if self.logy.isChecked():
            y = np.maximum(y, 1e-18)

        band = pg.LinearRegionItem([emin, emax], movable=False, brush=BAND)
        band.setZValue(-10)
        self.curve_plot.addItem(band)
        self.curve_plot.plot(E, y, pen=pg.mkPen(ACCEPT, width=2))

        # The filter is exactly 0.5 at each edge: an eigenvalue sitting there is
        # half-counted, which is the single most common way to get a confusing
        # answer out of FEAST.
        self.curve_plot.plot([emin, emax], [0.5, 0.5], pen=None, symbol="o",
                             symbolSize=7, symbolBrush=REJECT)

        if eig is not None and len(eig):
            ef = np.abs(C.filter_at(np.real(eig), emin, emax, points, rule))
            if self.logy.isChecked():
                ef = np.maximum(ef, 1e-18)
            self.curve_plot.plot(np.real(eig), ef, pen=None, symbol="d",
                                 symbolSize=8, symbolBrush=None,
                                 symbolPen=pg.mkPen("#222", width=1.5))

        Z, W = C.interval_contour(emin, emax, points, rule)
        self._draw_nodes(Z, W, extra_real=[emin, emax])
        sel = C.selectivity(emin, emax, points, rule)
        self.caption.setText(
            f"{C.RULE_NAMES[rule]}, {points} points on the half-contour. "
            f"Inside the interval the filter passes about {sel:.0f}x more "
            f"strongly than just outside it. It is exactly 0.5 at each edge "
            f"(orange), so an eigenvalue on the boundary counts as half -- "
            f"place edges in gaps. Diamonds are the eigenvalues found.")

    def _draw_disc(self, rule, points):
        _, centre, radius, eig = self._state
        Z, W = C.disc_contour(centre, radius, points, rule)
        self._draw_nodes(Z, W)

        # In the plane the filter is a surface, so sample it along a ray
        # outward from the centre -- the honest 1-D slice of a 2-D object.
        t = np.linspace(0.0, 3.0 * radius, 400)
        pts = centre + t
        y = C.disc_filter_at(pts, centre, radius, points, rule)
        if self.logy.isChecked():
            y = np.maximum(y, 1e-18)
        self.curve_plot.setLabel("bottom", "distance from centre")
        band = pg.LinearRegionItem([0, radius], movable=False, brush=BAND)
        band.setZValue(-10)
        self.curve_plot.addItem(band)
        self.curve_plot.plot(t, y, pen=pg.mkPen(ACCEPT, width=2))

        if eig is not None and len(eig):
            d = np.abs(np.asarray(eig, dtype=complex) - centre)
            ef = C.disc_filter_at(np.asarray(eig, dtype=complex), centre,
                                  radius, points, rule)
            if self.logy.isChecked():
                ef = np.maximum(ef, 1e-18)
            self.curve_plot.plot(d, ef, pen=None, symbol="d", symbolSize=8,
                                 symbolBrush=None,
                                 symbolPen=pg.mkPen("#222", width=1.5))
            self.contour_plot.plot(np.real(eig), np.imag(eig), pen=None,
                                   symbol="d", symbolSize=8,
                                   symbolBrush=ACCEPT)
        self.caption.setText(
            f"{C.RULE_NAMES[rule]}, {points} points around the full contour. "
            f"The curve is the filter along a ray from the centre outward; in "
            f"the plane it is a surface. Non-Hermitian searches use a closed "
            f"contour with no conjugate symmetry, so every point costs.")

    def _draw_nodes(self, Z, W, extra_real=()):
        # Node marker size carries |weight|: it shows at a glance that the
        # points do not contribute equally, which is the whole idea of a
        # quadrature rule.
        w = np.abs(W)
        size = 6 + 10 * (w / w.max() if w.max() > 0 else w)
        self.contour_plot.plot(Z.real, Z.imag, pen=pg.mkPen(MUTED, width=1,
                                                            style=Qt.DashLine),
                               symbol="o", symbolSize=list(size),
                               symbolBrush=ACCEPT, symbolPen=None)
        if len(extra_real) == 2:
            self.contour_plot.plot(list(extra_real), [0, 0], pen=None,
                                   symbol="+", symbolSize=12,
                                   symbolBrush=REJECT, symbolPen=REJECT)
        self.contour_plot.plot(Z.real, -Z.imag, pen=None, symbol="o",
                               symbolSize=4, symbolBrush=(140, 140, 140, 90),
                               symbolPen=None)


class MatrixView(QWidget):
    """What the matrix actually is: its shape, and the facts that pick a routine.

    For a small matrix the numbers themselves are the most useful thing on
    screen -- that is the whole point of FEAST's 4x4 hello-world. For anything
    larger the *pattern* carries the information: banded, block-structured,
    arrow-shaped, and how symmetric it really is.
    """

    NUMERIC_LIMIT = 24          # above this, a grid of numbers is unreadable

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setLayout(QHBoxLayout())
        self.image = pg.ImageView()
        self.image.ui.roiBtn.hide()
        self.image.ui.menuBtn.hide()
        self.image.ui.histogram.hide()
        self.numbers = QLabel("")
        self.numbers.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.numbers.setStyleSheet("font-family: monospace;")
        self.numbers.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.numbers.hide()
        self.facts = QLabel("No matrix loaded.")
        self.facts.setWordWrap(True)
        self.facts.setAlignment(Qt.AlignTop)
        self.facts.setMinimumWidth(280)
        self.facts.setMaximumWidth(360)
        self.layout().addWidget(self.image, 1)
        self.layout().addWidget(self.numbers, 1)
        self.layout().addWidget(self.facts)

    def show_matrix(self, A, B=None, uplo: str = "F", title: str = ""):
        if A is None:
            self.facts.setText("No matrix loaded.")
            return
        A = sp.csr_matrix(A)
        n = A.shape[0]

        if n <= self.NUMERIC_LIMIT:
            self.image.hide()
            self.numbers.show()
            self.numbers.setText(self._as_text(A))
        else:
            self.numbers.hide()
            self.image.show()
            self.image.setImage(self._pattern(A), autoLevels=True)

        self.facts.setText(self._describe(A, B, uplo, title, n))

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def _as_text(A) -> str:
        D = A.toarray()
        cplx = np.iscomplexobj(D)
        rows = []
        for r in D:
            if cplx:
                rows.append("  ".join(f"{v.real:6.2f}{v.imag:+.2f}i" for v in r))
            else:
                rows.append("  ".join(f"{v:8.3f}" for v in r))
        return "\n".join(rows)

    @staticmethod
    def _pattern(A, size: int = 700):
        """Bin the non-zeros into a fixed grid.

        Never build a dense n x n array: at n = 49,192 -- the largest problem
        FEAST ships -- that is 19 GB. Binning touches only the stored entries,
        so cost scales with nnz rather than n^2.
        """
        n = A.shape[0]
        k = min(size, n)
        Aco = A.tocoo()
        ri = (Aco.row.astype(np.int64) * k) // n
        ci = (Aco.col.astype(np.int64) * k) // n
        img = np.zeros((k, k), dtype=np.float32)
        np.add.at(img, (ri, ci), 1.0)
        # Log scale: a few dense blocks otherwise flatten everything else to 0.
        img = np.log1p(img)
        return img.T[:, ::-1]        # row 0 at the top, as a matrix is written

    @staticmethod
    def _describe(A, B, uplo, title, n) -> str:
        stored = A.nnz
        density = 100.0 * stored / (n * n) if n else 0.0
        parts = [f"<b>{title or 'matrix'}</b>", f"size {n} x {n}",
                 f"{stored:,} stored entries ({density:.3f}% of full)"]

        upper = sp.triu(A, k=1).nnz
        lower = sp.tril(A, k=-1).nnz
        if upper and not lower:
            parts.append("upper triangle only")
        elif lower and not upper:
            parts.append("lower triangle only")
        else:
            parts.append("both triangles stored")
        parts.append(f"declared to FEAST as uplo='{uplo}'")

        # Bandwidth decides whether the banded routines are even applicable.
        if stored:
            Aco = A.tocoo()
            bw = int(np.abs(Aco.row.astype(np.int64) - Aco.col).max())
            parts.append(f"bandwidth {bw}"
                         + (" (narrow -- banded routines apply)"
                            if bw < max(4, n // 20) else ""))

        if np.iscomplexobj(A.data):
            herm = (abs(A - A.getH()).max() if stored else 0.0) if uplo == "F" else None
            symm = (abs(A - A.T).max() if stored else 0.0) if uplo == "F" else None
            parts.append("complex values")
            if herm is not None:
                parts.append(f"max|A - A<sup>H</sup>| = {herm:.2e}")
                parts.append(f"max|A - A<sup>T</sup>| = {symm:.2e}")
                parts.append("<i>Hermitian</i>" if herm <= 1e-10 else
                             ("<i>complex symmetric</i>" if symm <= 1e-10
                              else "<i>general</i>"))
        else:
            parts.append("real values")
            if uplo == "F" and stored:
                asym = abs(A - A.T).max()
                parts.append(f"max|A - A<sup>T</sup>| = {asym:.2e}")
                parts.append("<i>symmetric</i>" if asym <= 1e-10 else "<i>general</i>")

        if B is not None:
            Bc = sp.csr_matrix(B)
            diag = Bc.nnz == Bc.diagonal().nonzero()[0].size
            parts.append(f"<br>B: {Bc.nnz:,} entries"
                         + (" (diagonal -- a lumped mass matrix)" if diag else ""))
            parts.append("generalized problem A x = &lambda; B x")
        else:
            parts.append("<br>standard problem A x = &lambda; x")
        return "<br>".join(parts)


class SpectrumView(QWidget):
    """Where the eigenvalues are, and how much each can be trusted.

    Replaces a plot whose vertical axis was "index" -- the row number after
    sorting, which is not a property of the problem and shifts whenever the
    interval changes. Residual is a real measured quantity per eigenvalue, so
    both axes now mean something and the plot answers "where are they" and "can
    I believe them" at once.
    """

    picked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setLayout(QVBoxLayout())
        self.layout().setContentsMargins(4, 4, 4, 4)
        self.plot = _plot("eigenvalue", "residual")
        self.plot.setLogMode(y=True)
        self.layout().addWidget(self.plot, 1)
        self.caption = QLabel("")
        self.caption.setWordWrap(True)
        self.caption.setStyleSheet(f"color: {MUTED};")
        self.layout().addWidget(self.caption)
        self._pts = None
        self._values = np.zeros(0)

    def show_result(self, values, residuals, emin=None, emax=None,
                    rejected=None, rejected_res=None, tol=None):
        self.plot.clear()
        values = np.asarray(values, dtype=float).ravel()
        residuals = np.asarray(residuals, dtype=float).ravel()
        self._values = values

        if emin is not None and emax is not None:
            band = pg.LinearRegionItem([emin, emax], movable=False, brush=BAND)
            band.setZValue(-10)
            self.plot.addItem(band)

        # A log axis drops non-positive values without saying so; a residual of
        # exactly 0 is a real (excellent) outcome, so floor it visibly instead.
        floor = 1e-18
        shown = np.maximum(residuals, floor)

        if tol:
            line = pg.InfiniteLine(pos=np.log10(tol), angle=0,
                                   pen=pg.mkPen(MUTED, style=Qt.DashLine))
            self.plot.addItem(line)

        if rejected is not None and len(rejected):
            rr = np.maximum(np.asarray(rejected_res, dtype=float).ravel(), floor)
            self.plot.plot(np.asarray(rejected, dtype=float).ravel(), rr,
                           pen=None, symbol="o", symbolSize=7,
                           symbolBrush=None, symbolPen=pg.mkPen(REJECT, width=1.5))

        self._pts = self.plot.plot(values, shown, pen=None, symbol="o",
                                   symbolSize=9, symbolBrush=ACCEPT,
                                   symbolPen=None)
        self._pts.sigPointsClicked.connect(self._clicked)

        msg = (f"{len(values)} eigenvalue(s) found. Height is the residual "
               f"-- how well each pair satisfies A x = λ B x -- so lower "
               f"is better and the dashed line is your tolerance.")
        if rejected is not None and len(rejected):
            msg += (f" Hollow markers are the {len(rejected)} subspace slots "
                    f"FEAST examined and rejected as outside the interval; "
                    f"they are what a large enough M0 buys you.")
        self.caption.setText(msg)

    def _clicked(self, _item, points):
        if not len(points):
            return
        x = points[0].pos().x()
        idx = int(np.argmin(np.abs(self._values - x)))
        self.picked.emit(idx)


class EigenvectorView(QWidget):
    """The eigenvector for a chosen eigenvalue.

    The app previously computed eigenvectors and never showed them. For the
    built-in Laplacian they are sine waves of increasing frequency, which is
    the moment the output stops being a table of numbers and starts being
    recognisable physics.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setLayout(QVBoxLayout())
        self.layout().setContentsMargins(4, 4, 4, 4)
        self.plot = _plot("component", "amplitude")
        self.layout().addWidget(self.plot, 1)
        self.caption = QLabel("Solve, then click an eigenvalue to see its "
                              "eigenvector.")
        self.caption.setWordWrap(True)
        self.caption.setStyleSheet(f"color: {MUTED};")
        self.layout().addWidget(self.caption)
        self._vectors = None
        self._values = None

    def set_result(self, values, vectors):
        self._values = np.asarray(values) if values is not None else None
        self._vectors = vectors
        self.plot.clear()
        if self._values is not None and len(self._values):
            self.show_index(0)

    def show_index(self, idx: int):
        self.plot.clear()
        if self._vectors is None or self._values is None:
            return
        if not (0 <= idx < self._vectors.shape[1]):
            return
        v = self._vectors[:, idx]
        x = np.arange(1, len(v) + 1)
        if np.iscomplexobj(v):
            self.plot.plot(x, v.real, pen=pg.mkPen(ACCEPT, width=1.5),
                           name="real")
            self.plot.plot(x, v.imag, pen=pg.mkPen(REJECT, width=1.5,
                                                   style=Qt.DashLine))
            extra = "  (solid = real part, dashed = imaginary)"
        else:
            self.plot.plot(x, v, pen=pg.mkPen(ACCEPT, width=1.5))
            extra = ""
        lam = self._values[idx]
        lam_txt = (f"{lam.real:.10g}{lam.imag:+.4g}i"
                   if np.iscomplexobj(self._values) else f"{lam:.10g}")
        self.caption.setText(
            f"Eigenvector {idx + 1} of {len(self._values)}, for λ = "
            f"{lam_txt}. {len(v)} components.{extra}")
