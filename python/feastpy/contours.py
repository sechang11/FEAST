"""The contour and the rational filter -- FEAST's two defining objects.

FEAST finds eigenvalues by integrating around a contour in the complex plane.
That integral acts as a *filter*: a function that is close to 1 for eigenvalues
inside the search region and close to 0 outside. Everything that makes FEAST
behave the way it does -- why more contour points help, why the subspace must
be bigger than the answer, why an interval edge should never sit on top of an
eigenvalue -- is visible in the shape of that filter.

FEAST ships routines whose only purpose is to hand you these two things, so you
can look at them without running a solve:

    zfeast_contour / zfeast_gcontour     the quadrature nodes and weights
    dfeast_rational / zfeast_grational   the filter's value at given points

They are cheap -- microseconds -- so a GUI can recompute them on every keystroke.

    from feastpy import contours
    E, rho = contours.filter_curve(0.0, 1.0, points=8)
    nodes, weights = contours.interval_contour(0.0, 1.0, points=8)
"""
from __future__ import annotations

import numpy as np

from . import raw

# Quadrature rules, fpm(16). Note fpm(17) is dead in v4.0: the kernel passes
# fpm(16) into the argument still named fpm17, so one setting governs both the
# Hermitian and the non-Hermitian case.
GAUSS = 0
TRAPEZOIDAL = 1
ZOLOTAREV = 2

RULE_NAMES = {GAUSS: "Gauss", TRAPEZOIDAL: "Trapezoidal", ZOLOTAREV: "Zolotarev"}

# Point counts each rule will accept, from the user guide's table for fpm(2).
_GAUSS_HALF = tuple(range(1, 21)) + (24, 32, 40, 48, 56)
# ... and for fpm(8), the full contour.
_GAUSS_FULL = tuple(range(2, 41)) + (48, 64, 80, 96, 112)


def legal_points(rule: int, full_contour: bool) -> tuple:
    """Point counts this rule accepts. Trapezoidal takes anything."""
    if rule == TRAPEZOIDAL:
        return ()                      # unrestricted
    return _GAUSS_FULL if full_contour else _GAUSS_HALF


def nearest_legal(points: int, rule: int, full_contour: bool) -> int:
    """Snap a requested point count to one the rule will actually accept."""
    allowed = legal_points(rule, full_contour)
    if not allowed:
        return max(2 if full_contour else 1, int(points))
    return min(allowed, key=lambda v: (abs(v - points), v))


def interval_contour(emin: float, emax: float, points: int = 8,
                     rule: int = GAUSS, ratio: int = 100):
    """Nodes and weights for a Hermitian interval search.

    Returns the UPPER HALF of the contour only -- that is what FEAST computes.
    A Hermitian spectrum is real, so the contour is symmetric about the real
    axis and the lower half follows by conjugation at no cost.
    """
    n = int(points)
    Zne = np.zeros(n, dtype=np.complex128)
    Wne = np.zeros(n, dtype=np.complex128)
    raw.call("zfeast_contour", Emin=float(emin), Emax=float(emax), fpm2=n,
             fpm16=int(rule), fpm18=int(ratio), Zne=Zne, Wne=Wne)
    return Zne, Wne


def disc_contour(center: complex, radius: float, points: int = 16,
                 rule: int = GAUSS, ratio: int = 100, rotation: int = 0):
    """Nodes and weights for a non-Hermitian disc search (the full contour).

    Zolotarev is not available here: the full-contour generator has no
    Zolotarev branch, and asking for it leaves the arrays uninitialised while
    the run still reports 'Zolotarev'. Refused rather than passed through.
    """
    if int(rule) == ZOLOTAREV:
        raise ValueError(
            "Zolotarev is Hermitian-only. The full-contour generator has no "
            "Zolotarev branch, so FEAST would leave the nodes uninitialised "
            "while still reporting the rule as Zolotarev. Use Gauss or "
            "Trapezoidal for a disc search.")
    n = int(points)
    Zne = np.zeros(n, dtype=np.complex128)
    Wne = np.zeros(n, dtype=np.complex128)
    c = complex(center)
    raw.call("zfeast_gcontour",
             Emid=np.array([c.real, c.imag], dtype=np.float64),
             r=float(radius), fpm8=n, fpm17=int(rule), fpm18=int(ratio),
             fpm19=int(rotation), Zne=Zne, Wne=Wne)
    return Zne, Wne


def filter_curve(emin: float, emax: float, points: int = 8, rule: int = GAUSS,
                 ratio: int = 100, samples: int = 601, pad: float = 1.0):
    """Sample the rational filter across and beyond a Hermitian interval.

    Returns (E, rho): the energies sampled and the filter's value at each. rho
    is ~1 inside [emin, emax], ~0 well outside, and exactly 0.5 at each end --
    which is why an interval edge should never be placed on an eigenvalue.

    `pad` extends the sampled range by that multiple of the interval width on
    each side, so the roll-off is visible rather than cropped.
    """
    emin, emax = float(emin), float(emax)
    width = emax - emin
    lo, hi = emin - pad * width, emax + pad * width
    E = np.linspace(lo, hi, int(samples))
    f = np.zeros(len(E), dtype=np.float64)
    raw.call("dfeast_rational", Emin=emin, Emax=emax, fpm2=int(points),
             fpm16=int(rule), fpm18=int(ratio), Eig=E.copy(), M0=len(E), f=f)
    return E, f


def filter_at(values, emin: float, emax: float, points: int = 8,
              rule: int = GAUSS, ratio: int = 100):
    """The filter's value at specific energies -- e.g. the eigenvalues found.

    Useful for showing *why* something outside the interval was pulled into the
    subspace: its filter value will be small but not zero.
    """
    E = np.ascontiguousarray(np.asarray(values, dtype=np.float64).ravel())
    if E.size == 0:
        return np.zeros(0)
    f = np.zeros(E.size, dtype=np.float64)
    raw.call("dfeast_rational", Emin=float(emin), Emax=float(emax),
             fpm2=int(points), fpm16=int(rule), fpm18=int(ratio),
             Eig=E.copy(), M0=E.size, f=f)
    return f


def disc_filter_at(values, center: complex, radius: float, points: int = 16,
                   rule: int = GAUSS, ratio: int = 100, rotation: int = 0):
    """The filter's magnitude at points in the complex plane."""
    Z = np.ascontiguousarray(np.asarray(values, dtype=np.complex128).ravel())
    if Z.size == 0:
        return np.zeros(0)
    f = np.zeros(Z.size, dtype=np.complex128)
    c = complex(center)
    raw.call("zfeast_grational",
             Emid=np.array([c.real, c.imag], dtype=np.float64),
             r=float(radius), fpm8=int(points), fpm17=int(rule),
             fpm18=int(ratio), fpm19=int(rotation),
             Eig=Z.copy(), M0=Z.size, f=f)
    return np.abs(f)


def selectivity(emin: float, emax: float, points: int = 8, rule: int = GAUSS,
                ratio: int = 100) -> float:
    """How many times more strongly the filter passes inside than outside.

    A single number for "how sharp is this filter", useful as a caption. On
    [0,1] with Gauss: about 70 at 4 points, 18,000 at 8, 5.6e7 at 16.
    """
    E, f = filter_curve(emin, emax, points, rule, ratio, samples=601, pad=1.0)
    width = emax - emin
    inside = np.abs(f[(E > emin + 0.05 * width) & (E < emax - 0.05 * width)])
    outside = np.abs(f[(E < emin - 0.25 * width) | (E > emax + 0.25 * width)])
    if inside.size == 0 or outside.size == 0 or outside.max() == 0:
        return float("inf")
    return float(inside.min() / outside.max())
