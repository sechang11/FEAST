"""Offline licensing for the FEAST desktop application.

Ed25519-signed keys, verified locally. No activation server, so nothing can go
down and lock a paying customer out of software they own.

The free tier is capped by problem size rather than by time or features: the
application does everything, and the limit is only reached on work big enough
to be worth paying for. Nothing expires, so it keeps demonstrating the product
indefinitely.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

# Licensing is an optional layer. If the crypto library is missing, or no
# signing key has been configured for this build, the application runs with no
# restrictions at all rather than refusing to start: an eigensolver should not
# be held hostage by its commercial packaging, and pre-licence builds (demos,
# evaluations, source checkouts) must behave like ordinary software.
try:
    from .keys import (License, LicenseError, check_for_machine, issue,
                       new_keypair, verify, PUBLIC_KEY_B64)
    _CRYPTO = True
except Exception:                       # cryptography not installed
    _CRYPTO = False
    PUBLIC_KEY_B64 = "REPLACE_WITH_YOUR_PUBLIC_KEY"

    class LicenseError(Exception):
        pass

    class License:                      # placeholder so type hints still work
        name = email = machine = tier = issued = updates_until = note = ""

from .machine import machine_id

#: True only when this build can actually check licences. When False nothing is
#: capped, nothing says "free version", and Help -> Licence explains why.
ENABLED = _CRYPTO and PUBLIC_KEY_B64 != "REPLACE_WITH_YOUR_PUBLIC_KEY"


def why_disabled() -> str:
    if not _CRYPTO:
        return ("Licensing is unavailable in this build: the cryptography "
                "package is not installed.")
    return ("This build has no signing key configured, so it runs without "
            "restrictions.")

# The build this source produced, used for the update entitlement check.
BUILD_DATE = date(2026, 8, 10)

# Free-tier ceilings. Deliberately well above the web calculator (dense 500,
# sparse 20k / 400k nnz) so the desktop app is genuinely useful unlicensed,
# and only real production problems hit the wall.
FREE_DENSE_N = 2_000
FREE_SPARSE_N = 100_000
FREE_NNZ = 2_000_000


@dataclass
class Status:
    licensed: bool
    license: Optional[License] = None
    error: str = ""

    @property
    def holder(self) -> str:
        if not self.license:
            return ""
        return f"{self.license.name} <{self.license.email}>"


def license_path() -> Path:
    """Where the licence is kept, per user."""
    override = os.environ.get("FEAST_LICENSE_FILE")
    if override:
        return Path(override)
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
    elif os.sys.platform == "darwin":
        base = Path.home() / "Library/Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "FEAST" / "license.key"


def load() -> Status:
    """Read and check the stored licence, if any."""
    if not ENABLED:
        return Status(licensed=True)     # unrestricted; nothing to check
    path = license_path()
    if not path.exists():
        return Status(licensed=False)
    try:
        lic = check_for_machine(path.read_text(encoding="utf-8"),
                                machine_id(), BUILD_DATE)
        return Status(licensed=True, license=lic)
    except LicenseError as exc:
        return Status(licensed=False, error=str(exc))
    except OSError as exc:
        return Status(licensed=False, error=f"could not read {path}: {exc}")


def install(text: str) -> Status:
    """Validate a pasted licence and store it. Raises LicenseError if invalid."""
    if not ENABLED:
        raise LicenseError(why_disabled())
    lic = check_for_machine(text, machine_id(), BUILD_DATE)
    path = license_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(text.split()) + "\n", encoding="utf-8")
    return Status(licensed=True, license=lic)


def remove() -> None:
    license_path().unlink(missing_ok=True)


def check_size(n: int, sparse: bool, nnz: int = 0) -> Optional[str]:
    """None if this problem is within the free tier, else why it is not."""
    if not ENABLED:
        return None
    if sparse:
        if n > FREE_SPARSE_N:
            return (f"This matrix is {n:,}x{n:,}. The free version handles sparse "
                    f"matrices up to {FREE_SPARSE_N:,}.")
        if nnz > FREE_NNZ:
            return (f"This matrix has {nnz:,} nonzeros. The free version handles "
                    f"up to {FREE_NNZ:,}.")
    elif n > FREE_DENSE_N:
        return (f"This matrix is {n:,}x{n:,}. The free version handles dense "
                f"matrices up to {FREE_DENSE_N:,}x{FREE_DENSE_N:,}.")
    return None


__all__ = ["License", "LicenseError", "Status", "BUILD_DATE", "check_size",
           "ENABLED", "why_disabled",
           "install", "license_path", "load", "machine_id", "remove",
           "issue", "verify", "new_keypair", "check_for_machine",
           "FREE_DENSE_N", "FREE_SPARSE_N", "FREE_NNZ"]
