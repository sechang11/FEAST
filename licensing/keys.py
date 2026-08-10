"""Issuing and verifying offline licence keys.

Ed25519 signatures: the seller holds the private key, the application embeds
only the public key. Verification is entirely offline -- no activation server,
nothing to keep running, and no outage that stops a paying customer working.

A licence is a signed payload:

    FEAST1-<base64url payload>.<base64url signature>

carrying who bought it, which machine it is bound to, and the date its update
entitlement runs out. It is long, so it is emailed as a file or pasted -- not
typed.

Perpetual with a year of updates falls out of `updates_until`: the application
checks its own build date against it. An old build keeps working forever; a
build released after the entitlement expires refuses the licence and says why.
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass, asdict
from datetime import date, datetime
from typing import Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey,
)

PREFIX = "FEAST1-"

# The seller's public key, embedded in the application. Replaced by
# `keygen.py --new-keypair`; the private half never ships.
PUBLIC_KEY_B64 = "REPLACE_WITH_YOUR_PUBLIC_KEY"


class LicenseError(Exception):
    """A licence that cannot be used, with a reason fit to show a user."""


@dataclass
class License:
    name: str
    email: str
    machine: str            # machine.machine_id(), or "" for an unbound licence
    tier: str = "standard"
    issued: str = ""        # ISO date
    updates_until: str = "" # ISO date; the app still runs after this
    note: str = ""

    def payload(self) -> bytes:
        # Canonical: sorted keys, no spaces. The bytes that get signed must be
        # reproducible or verification fails for reasons nobody can debug.
        return json.dumps(asdict(self), sort_keys=True,
                          separators=(",", ":")).encode("utf-8")

    @property
    def updates_until_date(self) -> Optional[date]:
        try:
            return datetime.fromisoformat(self.updates_until).date()
        except (ValueError, TypeError):
            return None

    def covers_build(self, build_date: date) -> bool:
        """Whether this licence entitles the buyer to a build of that date."""
        until = self.updates_until_date
        return until is None or build_date <= until


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def new_keypair() -> tuple[str, str]:
    """(private, public), both base64. Keep the private one offline."""
    priv = Ed25519PrivateKey.generate()
    priv_raw = priv.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption())
    pub_raw = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw)
    return _b64e(priv_raw), _b64e(pub_raw)


def issue(license: License, private_key_b64: str) -> str:
    """Sign a licence. Run by the seller when a payment arrives."""
    priv = Ed25519PrivateKey.from_private_bytes(_b64d(private_key_b64))
    payload = license.payload()
    return f"{PREFIX}{_b64e(payload)}.{_b64e(priv.sign(payload))}"


def verify(text: str, public_key_b64: str | None = None) -> License:
    """Check a licence and return it. Raises LicenseError with a usable reason."""
    text = "".join(text.split())            # tolerate email line wrapping
    if not text.startswith(PREFIX):
        raise LicenseError("That does not look like a FEAST licence key.")
    body = text[len(PREFIX):]
    if body.count(".") != 1:
        raise LicenseError("The licence key is incomplete or was truncated in transit.")

    payload_b64, sig_b64 = body.split(".")
    try:
        payload, signature = _b64d(payload_b64), _b64d(sig_b64)
    except Exception:
        raise LicenseError("The licence key is damaged. Copy it again in full.")

    key_b64 = public_key_b64 or PUBLIC_KEY_B64
    if key_b64 == "REPLACE_WITH_YOUR_PUBLIC_KEY":
        raise LicenseError("This build has no licence key configured "
                           "(the public key was never set).")
    try:
        Ed25519PublicKey.from_public_bytes(_b64d(key_b64)).verify(signature, payload)
    except InvalidSignature:
        raise LicenseError("This licence key is not valid. If you retyped it, "
                           "paste it instead -- a single wrong character fails.")
    except Exception as exc:
        raise LicenseError(f"The licence key could not be checked: {exc}")

    try:
        return License(**json.loads(payload))
    except Exception:
        raise LicenseError("The licence key is from a newer version of the app.")


def check_for_machine(text: str, this_machine: str,
                      build_date: Optional[date] = None,
                      public_key_b64: str | None = None) -> License:
    """Verify, then check it belongs to this machine and covers this build."""
    lic = verify(text, public_key_b64)
    if lic.machine and lic.machine != this_machine:
        raise LicenseError(
            "This licence is registered to a different computer.\n\n"
            f"It is for machine {lic.machine}, and this one is {this_machine}.\n"
            "Send the seller this machine's id and they will reissue it.")
    if build_date is not None and not lic.covers_build(build_date):
        raise LicenseError(
            f"This licence covers updates released up to {lic.updates_until}, "
            "and this version is newer.\n\n"
            "The version you bought keeps working; renew to use this one.")
    return lic
