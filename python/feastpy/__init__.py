"""feastpy -- Python interface to the FEAST eigenvalue solver."""
from . import codegen, diagnostics, matrixio, raw, results_io, runner
from ._lib import FeastLibraryNotFound, load
from .results_io import save_results
from .solver import (
    FeastError,
    FeastResult,
    eigh_interval,
    eig_disc,
    eig_polynomial,
    eigsh_interval,
    estimate_count,
    explain_info,
    spectral_bounds,
    spectral_disc,
    polynomial_disc,
)

__all__ = [
    "eigh_interval",
    "eigsh_interval",
    "eig_disc",
    "eig_polynomial",
    "raw",
    "estimate_count",
    "spectral_bounds",
    "spectral_disc",
    "polynomial_disc",
    "FeastResult",
    "FeastError",
    "FeastLibraryNotFound",
    "explain_info",
    "load",
    "save_results",
    "results_io",
    "diagnostics",
    "runner",
    "codegen",
    "matrixio",
]
__version__ = "0.1.0"
