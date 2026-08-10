"""Licence issuing and verification. Run: python licensing/test_licensing.py"""
import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import licensing
from licensing import keys as K
from licensing import machine

results = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'  ' + detail if detail else ''}")
    results.append(bool(ok))


print("licensing tests")
PRIV, PUB = K.new_keypair()
MACHINE = machine.machine_id()
TODAY = date.today()


def make(**kw):
    base = dict(name="Ada Lovelace", email="ada@example.org", machine=MACHINE,
                issued=TODAY.isoformat(),
                updates_until=(TODAY + timedelta(days=365)).isoformat())
    base.update(kw)
    return K.License(**base)


# --- the happy path ----------------------------------------------------------
key = K.issue(make(), PRIV)
back = K.verify(key, PUB)
check("a signed licence verifies", back.email == "ada@example.org", back.name)
check("key has the documented shape", key.startswith("FEAST1-") and key.count(".") == 1,
      f"{len(key)} chars")

# --- forgery -----------------------------------------------------------------
try:
    K.verify(key, K.new_keypair()[1])
    check("a different public key rejects the licence", False, "accepted!")
except K.LicenseError:
    check("a different public key rejects the licence", True)

tampered = key[: len(K.PREFIX) + 10] + ("A" if key[len(K.PREFIX) + 10] != "A" else "B") \
           + key[len(K.PREFIX) + 11:]
try:
    K.verify(tampered, PUB)
    check("a tampered payload is rejected", False, "accepted!")
except K.LicenseError:
    check("a tampered payload is rejected", True)

# Editing the payload to grant a longer entitlement must invalidate it -- this
# is the whole point of signing.
import base64, json
body = key[len(K.PREFIX):]
payload_b64, sig_b64 = body.split(".")
payload = json.loads(K._b64d(payload_b64))
payload["updates_until"] = "2099-01-01"
forged = K.PREFIX + K._b64e(json.dumps(payload, sort_keys=True,
                                       separators=(",", ":")).encode()) + "." + sig_b64
try:
    K.verify(forged, PUB)
    check("extending the entitlement by hand is rejected", False, "accepted!")
except K.LicenseError:
    check("extending the entitlement by hand is rejected", True)

for bad, label in [("", "empty"), ("hello", "not a licence"),
                   (K.PREFIX + "abc", "no signature"),
                   (K.PREFIX + "!!!.???", "damaged base64")]:
    try:
        K.verify(bad, PUB)
        check(f"rejects {label}", False, "accepted!")
    except K.LicenseError:
        check(f"rejects {label}", True)

# --- machine binding ---------------------------------------------------------
lic = K.check_for_machine(key, MACHINE, TODAY, PUB)
check("binds to this machine", lic.machine == MACHINE)

try:
    K.check_for_machine(key, "0000-0000-0000-0000", TODAY, PUB)
    check("refuses another machine", False, "accepted!")
except K.LicenseError as exc:
    check("refuses another machine", "different computer" in str(exc))

unbound = K.issue(make(machine=""), PRIV)
check("an unbound licence works anywhere",
      K.check_for_machine(unbound, "0000-0000-0000-0000", TODAY, PUB).machine == "")

# --- update entitlement ------------------------------------------------------
old = K.issue(make(updates_until=(TODAY - timedelta(days=1)).isoformat()), PRIV)
check("a lapsed licence still runs the build it covers",
      K.verify(old, PUB).covers_build(TODAY - timedelta(days=30)))
try:
    K.check_for_machine(old, MACHINE, TODAY, PUB)
    check("a lapsed licence refuses a newer build", False, "accepted!")
except K.LicenseError as exc:
    check("a lapsed licence refuses a newer build", "keeps working" in str(exc))

# --- machine id --------------------------------------------------------------
check("machine id is stable across calls", machine.machine_id() == MACHINE, MACHINE)
check("machine id is formatted for a human to read",
      len(MACHINE) == 19 and MACHINE.count("-") == 3, MACHINE)
check("machine id does not leak the raw identifier",
      machine.raw_id() not in MACHINE)

# --- free tier ---------------------------------------------------------------
check("small dense matrix is free", licensing.check_size(500, sparse=False) is None)
check("large dense matrix needs a licence",
      licensing.check_size(5000, sparse=False) is not None,
      str(licensing.check_size(5000, sparse=False))[:52])
check("free tier beats the web calculator", licensing.FREE_DENSE_N > 500)
check("big sparse matrix needs a licence",
      licensing.check_size(200_000, sparse=True, nnz=10) is not None)
check("many nonzeros need a licence",
      licensing.check_size(1000, sparse=True, nnz=9_000_000) is not None)

# --- storage round trip ------------------------------------------------------
with tempfile.TemporaryDirectory() as td:
    os.environ["FEAST_LICENSE_FILE"] = os.path.join(td, "license.key")
    K.PUBLIC_KEY_B64 = PUB                      # pretend this build shipped with it
    check("no licence installed initially", not licensing.load().licensed)
    st = licensing.install(key)
    check("installing a licence works", st.licensed and st.holder.startswith("Ada"))
    check("it is found on the next start", licensing.load().licensed)
    licensing.remove()
    check("removing it works", not licensing.load().licensed)
    # Email clients wrap long lines; that must not break a paying customer.
    wrapped = key[:40] + "\n" + key[40:90] + "\r\n  " + key[90:]
    check("survives being wrapped by an email client",
          licensing.install(wrapped).licensed)
    os.environ.pop("FEAST_LICENSE_FILE")

print(f"\n{sum(results)}/{len(results)} passed")
raise SystemExit(0 if all(results) else 1)
