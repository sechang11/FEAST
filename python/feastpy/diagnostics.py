"""Turning FEAST status codes into something a user can act on.

`explain_info` says what happened. This says what to do about it, and returns
the concrete parameter change so the app can offer a button rather than leaving
the user to work out which of M0, the contour, the tolerance or the interval
was at fault.

Suggestions are ordered most-likely-fix first.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from .solver import explain_info


def _fmt_c(z) -> str:
    """A complex number the way a person writes one: 1.5, 2i, 1.5+2i."""
    z = complex(z)
    re, im = z.real, z.imag
    if im == 0:
        return f"{re:g}"
    if re == 0:
        return f"{im:g}i"
    return f"{re:g}{'+' if im > 0 else '-'}{abs(im):g}i"


@dataclass
class Suggestion:
    """One thing to try. `param`/`value` is applied by the caller if present."""

    text: str
    param: Optional[str] = None      # m0 | max_loops | contour_points |
                                     # tol_exponent | interval
    value: Any = None

    @property
    def actionable(self) -> bool:
        return self.param is not None


@dataclass
class Diagnosis:
    info: int
    headline: str
    detail: str
    suggestions: list

    @property
    def ok(self) -> bool:
        return self.info == 0


def diagnose(result, *, n: int, m0: int, contour_points: int, tol_exponent: int,
             max_loops: int, emin: Optional[float] = None,
             emax: Optional[float] = None,
             center: Optional[complex] = None,
             radius: Optional[float] = None,
             bounds: Optional[tuple] = None,
             bounds_guaranteed: bool = True) -> Diagnosis:
    """Explain a FeastResult and propose fixes.

    The search region is either an interval (`emin`/`emax`, Hermitian) or a
    disc (`center`/`radius`, non-Hermitian and complex-symmetric). The advice
    has to follow it: telling someone to "widen the interval" when they are
    searching a disc names a control that is not on their screen, and the
    fix they actually need -- a larger radius, or a centre nearer the
    eigenvalues -- never gets mentioned.
    """
    info = result.info
    s: list = []
    disc = center is not None and radius is not None

    if disc:
        region = f"the disc of radius {radius:g} about {_fmt_c(center)}"
        wider = Suggestion(
            f"Search a wider disc (radius {radius * 2:g}).", "radius", radius * 2)
    else:
        region = "[%g, %g]" % (emin, emax) if emin is not None else "this region"
        wider = None

    if info == 0:
        detail = f"Found {result.n_found} eigenvalue(s) in {result.loops} loop(s)."
        # Converged by FEAST's criterion, but the residuals may still be poor --
        # worth saying so rather than presenting them as exact.
        if result.n_found and float(max(result.residuals)) > 1e-6:
            s.append(Suggestion(
                f"Largest residual is {max(result.residuals):.1e}, which is high. "
                f"Tightening the tolerance to 1e-{min(16, tol_exponent + 3)} may help.",
                "tol_exponent", min(16, tol_exponent + 3)))
            s.append(Suggestion(
                f"More contour points ({contour_points * 2}) usually improves accuracy "
                "per loop.", "contour_points", min(64, contour_points * 2)))
        return Diagnosis(info, "Success", detail, s)

    if info == 1:
        headline = "No eigenvalues in this disc" if disc \
            else "No eigenvalues in this interval"
        if disc:
            detail = (f"FEAST searched {region} and found nothing. Nothing in "
                      "the spectrum lies inside that circle -- for a "
                      "non-Hermitian matrix the eigenvalues can sit well off "
                      "the real axis, so a disc centred on it may miss them "
                      "entirely.")
        else:
            detail = ("FEAST searched %s and found nothing. The interval is "
                      "probably in a gap, or outside the spectrum." % region)
        # A subspace far too small to hold the interval's eigenvalues can make
        # FEAST report "none here" rather than "too small" -- observed on
        # Apple Silicon (Accelerate) where other platforms return info=3 for
        # the same input. Offer the M0 fix first when M0 looks implausible,
        # otherwise the user is told there is nothing here when there is.
        if m0 < max(10, n // 20):
            s.append(Suggestion(
                f"M0={m0} is very small for a matrix of size {n}; a subspace "
                "that small can miss eigenvalues entirely. Try "
                f"{min(n, max(10, n // 4))}.",
                "m0", min(n, max(10, n // 4))))
        if disc:
            s.append(wider)
            if bounds is not None:
                # For a disc, `bounds` is a Gershgorin (centre, radius). It
                # bounds A -- for a pencil the eigenvalues are scaled by B and
                # can lie far outside it, measured at 4 of 20 inside on a
                # random pencil. So the containment is claimed only where it
                # holds; promising a bound that is not one is worse than
                # offering no disc at all.
                claim = ("Every eigenvalue is inside it."
                         if bounds_guaranteed else
                         "For a generalized problem this bounds A rather than "
                         "the pencil, so treat it as a place to start.")
                s.append(Suggestion(
                    f"Try the disc from A's Gershgorin bound: radius "
                    f"{bounds[1]:.6g} about {_fmt_c(bounds[0])}. {claim}",
                    "disc", (complex(bounds[0]).real, complex(bounds[0]).imag,
                             float(bounds[1]))))
        elif bounds is not None:
            s.append(Suggestion(
                f"Search the whole spectrum [{bounds[0]:.6g}, {bounds[1]:.6g}] "
                "to see where the eigenvalues actually are.",
                "interval", (float(bounds[0]), float(bounds[1]))))
        if disc:
            return Diagnosis(info, headline, detail, s)
        s.append(Suggestion(
            'Use "How many are in here?" before solving - it estimates the count '
            "in a fraction of the time."))
        return Diagnosis(info, headline, detail, s)

    if info == 2:
        headline = "Did not converge"
        detail = (f"Hit the {max_loops}-loop limit with error {result.epsout:.2e}, "
                  f"short of the 1e-{tol_exponent} tolerance.")
        s.append(Suggestion(f"Allow more loops ({max_loops * 2}).",
                            "max_loops", min(200, max_loops * 2)))
        s.append(Suggestion(
            f"Use more contour points ({min(64, contour_points * 2)}). This is "
            "usually more effective than more loops: it improves the rational "
            "filter itself.", "contour_points", min(64, contour_points * 2)))
        s.append(Suggestion(
            f"Accept a looser tolerance (1e-{max(1, tol_exponent - 3)}).",
            "tol_exponent", max(1, tol_exponent - 3)))
        return Diagnosis(info, headline, detail, s)

    if info == 3:
        headline = "Subspace too small"
        suggested = min(n, max(m0 * 2, 10))
        detail = (f"M0={m0} cannot hold every eigenvalue in "
                  + ("the disc" if disc else "the interval")
                  + ", so the result is incomplete.")
        s.append(Suggestion(f"Raise M0 to {suggested} and solve again.",
                            "m0", suggested))
        if disc:
            # No stochastic estimator for a disc, so the interval advice would
            # point at a button that is not there. A smaller disc holds fewer
            # eigenvalues, which is the other way out of this.
            s.append(Suggestion(
                f"Or search a smaller disc (radius {radius / 2:g}), which has "
                "fewer eigenvalues in it to hold.", "radius", radius / 2))
        else:
            s.append(Suggestion(
                'Or estimate the count first with "How many are in here?" and let it '
                "size M0 for you."))
        return Diagnosis(info, headline, detail, s)

    if info in (4, 5, 6):
        headline = explain_info(info).capitalize()
        detail = ("The subspace was returned but is not fully usable. This "
                  "usually means M0 is too large relative to the number of "
                  "eigenvalues present, or the problem is close to singular.")
        s.append(Suggestion(f"Try a smaller M0 ({max(1, m0 // 2)}).",
                            "m0", max(1, m0 // 2)))
        return Diagnosis(info, headline, detail, s)

    if info == 200:
        if disc:
            return Diagnosis(info, "Invalid search disc",
                             f"The radius must be positive, got {radius:g}.",
                             [Suggestion("Use a positive radius.", "radius",
                                         abs(radius) or 1.0)])
        return Diagnosis(info, "Invalid interval",
                         f"E min ({emin:g}) must be less than E max ({emax:g}).",
                         [Suggestion("Swap the two values.", "interval",
                                     (min(emin, emax), max(emin, emax)))]
                         if emin != emax else [])

    if info == 201:
        headline = "Invalid subspace size"
        detail = f"M0 must satisfy 0 < M0 <= N, but M0={m0} and N={n}."
        s.append(Suggestion(f"Set M0 to {min(n, max(10, n // 4))}.",
                            "m0", min(n, max(10, n // 4))))
        return Diagnosis(info, headline, detail, s)

    if info == 202:
        return Diagnosis(info, "Invalid matrix size",
                         f"N must be positive, got {n}.", [])

    if 100 <= info <= 199:
        idx = info - 100
        return Diagnosis(info, "Invalid parameter",
                         f"FEAST rejected fpm({idx}). This is a bug in the app "
                         "rather than something you did.", [])

    if info == -1:
        return Diagnosis(info, "Out of memory",
                         "The solver could not allocate enough memory. A smaller "
                         "M0 needs less.",
                         [Suggestion(f"Try M0 = {max(1, m0 // 2)}.",
                                     "m0", max(1, m0 // 2))])

    if info in (-2, -3):
        hint = ("the matrix is not what FEAST expects: for a disc search it "
                "must be stored in full (both triangles), and B must be "
                "non-singular"
                if disc else
                "the matrix is not what FEAST expects: check that it is "
                "symmetric/Hermitian, and that B is positive definite")
        return Diagnosis(info, "Internal solver error",
                         explain_info(info) + f". This usually indicates {hint}.",
                         [])

    return Diagnosis(info, f"FEAST returned info={info}", explain_info(info), [])
