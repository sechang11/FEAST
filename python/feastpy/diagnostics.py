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
             max_loops: int, emin: float, emax: float,
             bounds: Optional[tuple] = None) -> Diagnosis:
    """Explain a FeastResult and propose fixes."""
    info = result.info
    s: list = []

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
        headline = "No eigenvalues in this interval"
        detail = ("FEAST searched [%g, %g] and found nothing. The interval is "
                  "probably in a gap, or outside the spectrum." % (emin, emax))
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
        if bounds is not None:
            s.append(Suggestion(
                f"Search the whole spectrum [{bounds[0]:.6g}, {bounds[1]:.6g}] "
                "to see where the eigenvalues actually are.",
                "interval", (float(bounds[0]), float(bounds[1]))))
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
        detail = (f"M0={m0} cannot hold every eigenvalue in the interval, so the "
                  "result is incomplete.")
        s.append(Suggestion(f"Raise M0 to {suggested} and solve again.",
                            "m0", suggested))
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
        return Diagnosis(info, "Internal solver error",
                         explain_info(info) + ". This usually indicates the "
                         "matrix is not what FEAST expects: check that it is "
                         "symmetric/Hermitian, and that B is positive definite.",
                         [])

    return Diagnosis(info, f"FEAST returned info={info}", explain_info(info), [])
