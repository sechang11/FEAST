"""Issue licence keys. Run by the seller, offline.

    python -m licensing.keygen --new-keypair
    python -m licensing.keygen --name "Ada Lovelace" --email ada@example.org \\
                               --machine A1B2-C3D4-E5F6-7890

The private key lives in licensing/private_key.txt (gitignored) or
FEAST_LICENSE_PRIVATE_KEY. It must never ship in the application: anyone
holding it can mint licences.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from licensing.keys import License, PREFIX, issue, new_keypair, verify  # noqa: E402

HERE = Path(__file__).resolve().parent
PRIVATE_FILE = HERE / "private_key.txt"
ISSUED_LOG = HERE / "issued.csv"


def load_private() -> str:
    key = os.environ.get("FEAST_LICENSE_PRIVATE_KEY")
    if key:
        return key.strip()
    if PRIVATE_FILE.exists():
        return PRIVATE_FILE.read_text().strip()
    raise SystemExit(
        f"No private key. Create one with:\n"
        f"    python -m licensing.keygen --new-keypair\n"
        f"and keep {PRIVATE_FILE} somewhere safe and backed up.")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Issue a FEAST licence key")
    ap.add_argument("--new-keypair", action="store_true",
                    help="generate a signing keypair (run once, ever)")
    ap.add_argument("--name")
    ap.add_argument("--email")
    ap.add_argument("--machine", default="",
                    help="the machine id the buyer sent; omit for an unbound licence")
    ap.add_argument("--tier", default="standard")
    ap.add_argument("--updates-years", type=float, default=1.0,
                    help="years of updates included (default 1)")
    ap.add_argument("--note", default="", help="recorded in the licence, e.g. an order reference")
    args = ap.parse_args(argv)

    if args.new_keypair:
        if PRIVATE_FILE.exists():
            raise SystemExit(
                f"{PRIVATE_FILE} already exists. Generating a new keypair would "
                "invalidate every licence already issued. Delete it deliberately "
                "if that is really what you want.")
        priv, pub = new_keypair()
        PRIVATE_FILE.write_text(priv + "\n", encoding="utf-8")
        try:
            os.chmod(PRIVATE_FILE, 0o600)
        except OSError:
            pass
        print(f"private key written to {PRIVATE_FILE}  (back this up; never ship it)")
        print("\nPaste this public key into licensing/keys.py as PUBLIC_KEY_B64:\n")
        print(f"    PUBLIC_KEY_B64 = \"{pub}\"\n")
        return 0

    if not (args.name and args.email):
        ap.error("--name and --email are required (or use --new-keypair)")

    today = date.today()
    lic = License(
        name=args.name.strip(),
        email=args.email.strip(),
        machine=args.machine.strip().upper(),
        tier=args.tier,
        issued=today.isoformat(),
        updates_until=(today + timedelta(days=int(365 * args.updates_years))).isoformat(),
        note=args.note,
    )
    key = issue(lic, load_private())

    # Verify what we just produced before sending it to a paying customer.
    back = verify(key)
    assert back == lic, "the issued key did not verify -- do not send it"

    with ISSUED_LOG.open("a", encoding="utf-8") as fh:
        if fh.tell() == 0:
            fh.write("issued,name,email,machine,tier,updates_until,note\n")
        fh.write(f"{lic.issued},{lic.name},{lic.email},{lic.machine},"
                 f"{lic.tier},{lic.updates_until},{lic.note}\n")

    print(f"Licence for {lic.name} <{lic.email}>")
    print(f"  machine       : {lic.machine or '(not bound to a machine)'}")
    print(f"  updates until : {lic.updates_until}")
    print(f"  logged to     : {ISSUED_LOG}")
    print("\n--- send everything between the lines ---")
    print(key)
    print("--- end ---")
    return 0


if __name__ == "__main__":
    sys.exit(main())
