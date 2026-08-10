"""feastpy -- Python interface to the FEAST eigenvalue solver."""
from ._lib import FeastLibraryNotFound, load
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
]
__version__ = "0.1.0"
