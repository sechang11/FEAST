"""A stable identifier for this machine.

Machine-locked licences need an id that survives reboots, app updates and disk
changes, but differs on a new computer. Every platform has an OS-assigned
install id that fits; MAC address is the fallback and the least stable, since
docking stations and VPNs add adapters.

The raw id never leaves the machine: what the buyer sends is a truncated
salted hash, which is enough to bind a licence and not enough to identify the
hardware.
"""
from __future__ import annotations

import hashlib
import platform
import subprocess
import sys
import uuid

# Changing this invalidates every machine id, and therefore every issued
# licence. Do not change it after the first sale.
_SALT = b"feast-desktop-machine-id-v1"


def _windows_id() -> str | None:
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                             r"SOFTWARE\Microsoft\Cryptography", 0,
                             winreg.KEY_READ | winreg.KEY_WOW64_64KEY)
        with key:
            return winreg.QueryValueEx(key, "MachineGuid")[0]
    except Exception:
        return None


def _linux_id() -> str | None:
    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            with open(path) as fh:
                value = fh.read().strip()
            if value:
                return value
        except OSError:
            continue
    return None


def _macos_id() -> str | None:
    try:
        out = subprocess.run(["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                             capture_output=True, text=True, timeout=10).stdout
        for line in out.splitlines():
            if "IOPlatformUUID" in line:
                return line.split('"')[-2]
    except Exception:
        return None
    return None


def raw_id() -> str:
    """The OS-assigned install id, or a MAC-address fallback."""
    getter = {"win32": _windows_id, "darwin": _macos_id}.get(sys.platform, _linux_id)
    value = getter()
    if value:
        return value
    # uuid.getnode() invents a random node id if it cannot find a MAC, which
    # would change every run; that is worse than useless for binding, so mark it.
    node = uuid.getnode()
    return f"mac:{node:012x}"


def machine_id() -> str:
    """The short, salted, non-reversible id a licence is bound to."""
    digest = hashlib.sha256(_SALT + raw_id().encode("utf-8")).hexdigest()
    short = digest[:16].upper()
    return "-".join(short[i:i + 4] for i in range(0, 16, 4))


def describe() -> str:
    return f"{platform.system()} {platform.machine()}  id {machine_id()}"


if __name__ == "__main__":
    print(describe())
