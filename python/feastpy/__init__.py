"""feastpy -- Python interface to the FEAST eigenvalue solver."""
from . import codegen, diagnostics, matrixio, results_io, runner
from ._lib import FeastLibraryNotFound, load
from .results_io import save_results
from .solver import (
    FeastError,
    FeastResult,
    eigh_interval,
    eigsh_interval,
    estimate_count,
    explain_info,
    spectral_bounds,
)

__all__ = [
    "eigh_interval",
    "eigsh_interval",
    "estimate_count",
    "spectral_bounds",
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
