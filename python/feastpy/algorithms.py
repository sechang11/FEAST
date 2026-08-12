"""The algorithmic choices FEAST offers, with explanations a GUI can show.

FEAST is not one algorithm with a tolerance knob. It is a contour-integration
scheme whose behaviour changes substantially with the quadrature rule, the
contour shape, the number of nodes, and whether the inner linear systems are
solved directly or iteratively. The user guide documents the parameters; it
does not really explain which to reach for, and several of the most useful ones
are not documented at all.

Every entry below was checked against the v4.0 guide (arXiv 2002.04807) AND
against the source, and where the two disagree the source wins. Those
disagreements are called out in `caveat` -- they are the ones most likely to
waste somebody's afternoon.

    from feastpy import algorithms
    for opt in algorithms.for_problem(hermitian=True):
        print(opt.label, opt.summary)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Choice:
    """One selectable value of an option."""
    value: int
    label: str
    detail: str
    caveat: str = ""


@dataclass(frozen=True)
class Option:
    key: str                     # fpm slot, e.g. "fpm(16)", or a pseudo-key
    label: str                   # what to put on the control
    summary: str                 # one line, safe to show as a caption
    detail: str                  # the paragraph behind a "?" / hover
    applies: str                 # "hermitian", "nonhermitian", "both"
    tier: str                    # "primary", "advanced", "expert"
    choices: tuple = ()          # for enumerated options
    minimum: Optional[int] = None
    maximum: Optional[int] = None
    default_text: str = ""
    caveat: str = ""


# --------------------------------------------------------------- the options
QUADRATURE = Option(
    key="fpm(16)", label="Quadrature rule", applies="both", tier="primary",
    summary="Where the integration points sit on the contour.",
    detail=(
        "FEAST builds a filter that should be 1 inside your search region and "
        "0 outside, by integrating around a contour. The rule decides where "
        "the points go, and that decides how sharply the filter cuts off.\n\n"
        "Gauss-Legendre concentrates points where they buy the most accuracy "
        "and is the best general choice for a Hermitian interval. Trapezoidal "
        "spaces them evenly and accepts any number of points. Zolotarev is "
        "optimal in a minimax sense -- it makes the filter uniformly small "
        "across the whole rest of the spectrum rather than dropping fastest "
        "just outside your interval -- which is why the guide recommends it "
        "for continuum spectra: it converges without needing M0 much larger "
        "than M.\n\n"
        "Measured just outside [0,1] at 8 points, Gauss suppresses by about "
        "4600x, Trapezoidal 620x and Zolotarev 90x. That ordering reverses far "
        "from the interval, which is exactly the trade Zolotarev makes -- so "
        "judge it by whether it converges at a small M0, not by the edge."),
    default_text="Gauss for Hermitian FEAST; Trapezoidal for non-Hermitian and "
                 "for all IFEAST runs.",
    choices=(
        Choice(0, "Gauss-Legendre",
               "Best general choice for a Hermitian interval with a clear gap "
               "between wanted and unwanted eigenvalues."),
        Choice(1, "Trapezoidal",
               "Evenly spaced. Accepts any number of points, where Gauss and "
               "Zolotarev only accept certain counts."),
        Choice(2, "Zolotarev",
               "Sharpest cutoff for the money. Ideal for continuous spectra, "
               "and converges without inflating M0.",
               caveat="Hermitian problems only. Selecting it for a "
                      "non-Hermitian or polynomial problem is not rejected, "
                      "but the full-contour generator has no Zolotarev branch, "
                      "so the nodes are left uninitialised while the banner "
                      "still claims 'Zolotarev'."),
    ),
    caveat=(
        "fpm(17) is dead in v4.0. The guide's parameter table jumps from 16 to "
        "18, the source marks fpm(17) deprecated, and the kernel passes "
        "fpm(16) into the argument still named fpm17 (dzfeast.f90:4602). One "
        "knob governs both the Hermitian and the non-Hermitian rule."),
)

CONTOUR_POINTS_H = Option(
    key="fpm(2)", label="Contour points (half-contour)", applies="hermitian",
    tier="primary", minimum=1, maximum=56,
    summary="How many integration points on the upper half of the contour.",
    detail=(
        "The first thing to increase when FEAST converges slowly -- the "
        "guide's own tip list says to 'keep on increasing' it. Each point "
        "costs one linear system solve per refinement loop, so the cost is "
        "linear, while the filter sharpens roughly exponentially.\n\n"
        "A Hermitian spectrum is real, so the contour is symmetric about the "
        "real axis and FEAST only needs the upper half; the lower half is "
        "obtained by conjugation for free. Measured on [0,1]: 4 points "
        "separate inside from outside by a factor of 70, 8 points by 18,000, "
        "16 points by 56 million."),
    default_text="8 for FEAST, 4 for IFEAST, 3 when estimating the count.",
    caveat="With Gauss or Zolotarev only 1-20, 24, 32, 40, 48 and 56 are "
           "accepted. Trapezoidal takes any positive number.",
)

CONTOUR_POINTS_G = Option(
    key="fpm(8)", label="Contour points (full contour)", applies="nonhermitian",
    tier="primary", minimum=2, maximum=112,
    summary="How many integration points around the whole contour.",
    detail=(
        "The non-Hermitian equivalent of fpm(2). Because the eigenvalues are "
        "scattered in the complex plane, the contour is a closed curve with no "
        "conjugate symmetry to exploit, so every point must be computed -- a "
        "full contour with N points costs about twice a half-contour with N."),
    default_text="16 for FEAST, 8 for IFEAST, 6 when estimating the count.",
    caveat="With Gauss only 2-40, 48, 64, 80, 96 and 112 are accepted.",
)

ELLIPSE_RATIO = Option(
    key="fpm(18)", label="Contour shape (ratio x100)", applies="both",
    tier="advanced", minimum=0, maximum=400,
    summary="Flattens or rounds the contour. 100 is a circle.",
    detail=(
        "The contour is an ellipse. This sets its vertical axis as a "
        "percentage of its horizontal one, so 100 is a circle and 30 is a "
        "flattened ellipse hugging the search axis.\n\n"
        "Flat is good for Hermitian problems: the eigenvalues are all on the "
        "real axis, so pulling the contour close to that axis sharpens the "
        "cutoff at the interval ends. It is the wrong instinct for a "
        "non-Hermitian problem, where the eigenvalues genuinely spread into "
        "the plane and a flattened contour would miss them."),
    default_text="30 (a flat ellipse) for Hermitian FEAST; 100 (a circle) for "
                 "non-Hermitian, polynomial, and all IFEAST runs.",
    caveat="Ignored by Zolotarev, which is always a circle.",
)

ELLIPSE_ROTATION = Option(
    key="fpm(19)", label="Contour rotation (degrees)", applies="nonhermitian",
    tier="advanced", minimum=-180, maximum=180,
    summary="Rotates the search ellipse about its centre.",
    detail=(
        "Turns the ellipse. Useful when the eigenvalues you want lie along a "
        "tilted line or arc in the complex plane rather than parallel to an "
        "axis -- damped and gyroscopic systems do this routinely. Combined "
        "with a flattened ratio it lets you wrap a narrow contour tightly "
        "around a diagonal string of eigenvalues instead of enclosing a large "
        "circle full of ones you did not ask for."),
    default_text="0",
)

SUBSPACE = Option(
    key="M0", label="Subspace size M0", applies="both", tier="primary",
    minimum=1,
    summary="How many columns FEAST carries. Must exceed the number of "
            "eigenvalues in your region.",
    detail=(
        "M0 is an over-estimate of M, the number of eigenvalues actually "
        "inside your search region. The guide asks for M0 >= 1.5*M.\n\n"
        "The reason is the filter. It is not exactly 1 inside and 0 outside; "
        "it decays smoothly, so eigenvalues just beyond your region leak into "
        "the subspace and take up room. If M0 is too tight there is nowhere "
        "for them to go and convergence suffers. Too small outright returns "
        "info=3.\n\n"
        "After M0, raising the contour point count is the next lever."),
    default_text="No default -- you must supply it. Use the count estimate to "
                 "size it.",
    caveat="M0 must be strictly greater than M, not equal. FEAST's own 4x4 "
           "hello-world ships M0=2 for a problem with 2 eigenvalues and duly "
           "returns the info=3 warning.",
)

STOP_TOL = Option(
    key="fpm(3)", label="Stopping tolerance (10^-n)", applies="both",
    tier="primary", minimum=0, maximum=16,
    summary="Convergence threshold. 12 means 1e-12.",
    detail=(
        "How small the convergence measure must get before FEAST stops. "
        "Loosen it to 6-8 for a quick exploratory run, or when the matrix "
        "itself only carries a few correct digits -- there is no sense "
        "converging to 1e-12 on data good to 1e-4."),
    default_text="12",
)

CONVERGENCE_TEST = Option(
    key="fpm(6)", label="Convergence measured by", applies="both",
    tier="advanced",
    summary="Whether 'converged' means a stable trace or small residuals.",
    detail=(
        "Two different definitions of done, and they are not equally "
        "trustworthy.\n\n"
        "The trace test watches |trace_k - trace_(k-1)|, the change in the sum "
        "of the eigenvalues between iterations. It is cheap, but it measures "
        "that the answer stopped moving -- not that it is right. An iteration "
        "can settle onto an incomplete subspace and look perfectly converged.\n\n"
        "The residual test measures how well each computed pair actually "
        "satisfies Ax = lambda Bx. It costs more and it is the honest one."),
    default_text="Residual",
    choices=(
        Choice(0, "Relative trace error",
               "Cheap and aggregate. Use when you only need the trace itself, "
               "such as a total energy."),
        Choice(1, "Relative residual",
               "Per-eigenpair and honest. Use for any result you will rely on."),
    ),
)

MAX_LOOPS = Option(
    key="fpm(4)", label="Maximum refinement loops", applies="both",
    tier="advanced", minimum=0,
    summary="Hard cap on outer iterations before giving up.",
    detail=(
        "Hitting the cap sets info=2 ('no convergence'), but FEAST still "
        "returns the best eigenpairs it reached -- so a run that hits the cap "
        "is not worthless, it is unfinished. Raise it when you have "
        "deliberately chosen a cheap-per-loop configuration."),
    default_text="20 for FEAST, 50 for IFEAST.",
)

INNER_SOLVER = Option(
    key="fpm(43)", label="Inner linear solver", applies="both", tier="primary",
    summary="Direct factorization, or iterative BiCGStab.",
    detail=(
        "Every contour point requires solving a shifted linear system. FEAST "
        "factorizes it once with a direct sparse solver; IFEAST solves it "
        "iteratively and never forms a factorization.\n\n"
        "Direct is faster per loop and far more robust -- it is the right "
        "choice whenever the factorization fits in memory. Iterative wins on "
        "very large problems where the fill-in of a direct factorization would "
        "be ruinous, and it is the only option in a build without MKL."),
    default_text="Direct where available.",
    choices=(
        Choice(0, "Direct (PARDISO)",
               "Factorize once per contour point, reuse every loop."),
        Choice(1, "Iterative (BiCGStab)",
               "No factorization. Scales to problems a direct solver cannot "
               "hold, at the cost of robustness on badly conditioned or "
               "strongly non-normal matrices."),
    ),
    caveat="The libraries we ship contain no PARDISO, so this control has one "
           "reachable state and every run is iterative. Building against Intel "
           "MKL is what unlocks the direct path.",
)

MIXED_PRECISION = Option(
    key="fpm(42)", label="Single-precision inner solves", applies="both",
    tier="advanced",
    summary="Solve the inner systems in single precision. On by default.",
    detail=(
        "This looks reckless and is not. Version 4.0 uses residual inverse "
        "iteration, in which the inner systems only need to be solved "
        "roughly -- the outer iteration corrects the error. So they are solved "
        "in single precision by default, at half the memory and bandwidth, "
        "with no loss in the final double-precision accuracy.\n\n"
        "Turn it off only when the shifted matrix is so ill-conditioned that "
        "single precision has nothing left to give."),
    default_text="On",
    choices=(Choice(1, "On (single)", "Default. Faster, same final accuracy."),
             Choice(0, "Off (double)", "For severely ill-conditioned systems.")),
)

STORE_FACTORS = Option(
    key="fpm(10)", label="Keep factorizations in memory", applies="both",
    tier="advanced",
    summary="Reuse each contour point's factorization across loops.",
    detail=(
        "The shifted matrix at each contour point is identical in every outer "
        "iteration -- only the right-hand sides change. Storing the "
        "factorizations avoids redoing the expensive part every loop, at the "
        "cost of holding one factorization per contour point in memory at "
        "once. Turn it off when they do not fit."),
    default_text="On for the driver interfaces.",
    choices=(Choice(1, "Keep", "Much faster; needs memory for every point."),
             Choice(0, "Refactorize", "Slower, but holds only one at a time.")),
)

EXTREME_SEARCH = Option(
    key="fpm(40)", label="Search mode", applies="hermitian", tier="primary",
    summary="Give an interval, or just ask for the lowest/highest eigenvalues.",
    detail=(
        "FEAST normally wants an interval, which assumes you know roughly "
        "where to look. For the common case of 'I want the 20 lowest modes' "
        "with no idea of their range, the Hermitian sparse drivers can find "
        "the extremes themselves and hand back the interval they used. Set M0 "
        "to twice the number you want."),
    default_text="User-supplied interval.",
    choices=(
        Choice(0, "Interval I specify", "The normal mode."),
        Choice(-1, "Lowest M0/2 eigenvalues",
               "Finds the bottom of the spectrum and returns the interval."),
        Choice(1, "Highest M0/2 eigenvalues", "The same, at the top."),
    ),
)

COUNT_ESTIMATE = Option(
    key="fpm(14)", label="Estimate the count first", applies="both",
    tier="primary",
    summary="Cheaply guess how many eigenvalues are in the region.",
    detail=(
        "Runs a stochastic (Hutchinson-style) estimate of how many eigenvalues "
        "lie inside the contour, without solving for any of them. This is how "
        "you size M0 on an unfamiliar spectrum instead of guessing.\n\n"
        "It is an estimate, not a count. It is cheap, but it is not free."),
    default_text="Off (normal execution).",
    choices=(
        Choice(0, "Normal run", ""),
        Choice(1, "Return the subspace only", "Stops after one contour."),
        Choice(2, "Estimate the count", "Returns an estimate and exits."),
    ),
    caveat=(
        "Repeating it does not give you an error bar. The random seed is "
        "hard-coded, so in a serial run every repeat returns exactly the same "
        "number -- measured five identical results on three different "
        "problems. The estimate is also truncated rather than rounded, so it "
        "biases low: on FEAST's own system1, which has 16 eigenvalues in "
        "range, it reports 13. Size M0 above the estimate, not at it."),
)

LEFT_VECTORS = Option(
    key="fpm(15)", label="Left eigenvectors", applies="nonhermitian",
    tier="advanced",
    summary="Whether to compute left eigenvectors as well as right.",
    detail=(
        "A non-Hermitian matrix has distinct left and right eigenvectors, and "
        "the projection step needs a matching pair. Computing both means a "
        "second contour integration and roughly doubles the cost. For a "
        "complex symmetric matrix the left vectors are the conjugates of the "
        "right ones, so they come free."),
    default_text="Two-sided for general matrices; one-sided for complex "
                 "symmetric.",
    choices=(
        Choice(0, "Two-sided (compute both)", "Correct for a general matrix."),
        Choice(1, "One-sided (right only)", "Half the cost, if you only need right."),
        Choice(2, "One-sided, left = conj(right)", "Free and exact for complex symmetric."),
    ),
)

IFEAST_ACCURACY = Option(
    key="fpm(45)", label="Inner solver accuracy (10^-n)", applies="both",
    tier="expert", minimum=0, maximum=16,
    summary="How hard BiCGStab tries on each inner system. Default 1, i.e. 0.1.",
    detail=(
        "A tolerance of 0.1 looks like a typo. It is not: with residual "
        "inverse iteration the outer loop cleans up the inner solver's error, "
        "so solving to one digit is enough and solving harder is wasted work.\n\n"
        "Raise it to 2 or 3 if the outer iteration stalls or oscillates, which "
        "is the signature of inner solutions too rough to make progress."),
    default_text="1 (tolerance 0.1)",
)

IFEAST_MAX_ITER = Option(
    key="fpm(46)", label="Inner solver iteration cap", applies="both",
    tier="expert", minimum=1,
    summary="Maximum BiCGStab iterations per linear system.",
    detail=(
        "With the accuracy setting this means 'reach the tolerance or give up "
        "after this many iterations, whichever comes first'. Raise it for "
        "ill-conditioned shifted systems where the cap is hit before the "
        "tolerance."),
    default_text="40",
)

PRECONDITIONER = Option(
    key="fpm(44)", label="Inner preconditioner", applies="both", tier="expert",
    summary="Optional diagonal preconditioner for the iterative solver.",
    detail=(
        "Scales the shifted matrix by its own diagonal before iterating. It "
        "costs essentially nothing to set up and helps whenever the diagonal "
        "varies widely in magnitude -- which is most finite-element and "
        "quantum-chemistry matrices. Worth trying whenever the inner solver "
        "keeps hitting its iteration cap."),
    default_text="None",
    choices=(Choice(0, "None", "Plain BiCGStab."),
             Choice(1, "Jacobi (diagonal)", "Nearly free; often a large win.")),
    caveat="Undocumented: it appears nowhere in the user guide. Read out of "
           "feast_tools.f90 and libnum.f90.",
)

INITIAL_GUESS = Option(
    key="fpm(5)", label="Reuse previous subspace", applies="both",
    tier="advanced",
    summary="Start from the last answer instead of random vectors.",
    detail=(
        "FEAST normally starts from random vectors. When you are solving a "
        "series of related problems -- a parameter sweep, a self-consistent "
        "field loop, successive time steps -- the previous solution is an "
        "excellent starting point and can cut the loop count sharply."),
    default_text="Off (random start).",
    choices=(Choice(0, "Random start", "Reproducible: the seed is fixed."),
             Choice(1, "Use the previous result", "For a sequence of similar problems.")),
)

ALL: tuple = (
    SUBSPACE, QUADRATURE, CONTOUR_POINTS_H, CONTOUR_POINTS_G, STOP_TOL,
    INNER_SOLVER, EXTREME_SEARCH, COUNT_ESTIMATE,
    ELLIPSE_RATIO, ELLIPSE_ROTATION, CONVERGENCE_TEST, MAX_LOOPS,
    MIXED_PRECISION, STORE_FACTORS, LEFT_VECTORS, INITIAL_GUESS,
    IFEAST_ACCURACY, IFEAST_MAX_ITER, PRECONDITIONER,
)

BY_KEY = {o.key: o for o in ALL}


def for_problem(hermitian: bool, tier: Optional[str] = None) -> list:
    """Options that apply to this problem class, in presentation order."""
    want = "hermitian" if hermitian else "nonhermitian"
    out = [o for o in ALL if o.applies in ("both", want)]
    if tier:
        out = [o for o in out if o.tier == tier]
    return out


def tiers() -> tuple:
    return ("primary", "advanced", "expert")


TIER_LABELS = {
    "primary": "Main settings",
    "advanced": "Advanced",
    "expert": "Iterative solver (expert)",
}
