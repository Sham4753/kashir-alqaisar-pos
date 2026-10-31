#!/usr/bin/env python3
"""Generate offline CAESAR POS licenses using an externally held Ed25519 key."""
import argparse
import base64
from getpass import getpass
import os
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent / "app"
sys.path.insert(0, str(APP_DIR))

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from license_crypto import license_message, license_number_for, normalize_machine_id  # noqa: E402

PRIVATE_KEY_ENV = "CAESAR_LICENSE_PRIVATE_KEY_PATH"


def load_private_key(path):
    """Read only the caller-selected vendor key; there is no fallback or default."""
    try:
        pem = Path(path).expanduser().read_bytes()
    except OSError as exc:
        raise SystemExit(f"Cannot read the selected vendor key file: {exc}") from exc
    if b"-----BEGIN ENCRYPTED PRIVATE KEY-----" not in pem:
        raise SystemExit("The vendor signing key must be passphrase-encrypted; create it with tools/create_vendor_keys.py.")
    passphrase = getpass("Vendor private-key passphrase: ")
    try:
        key = serialization.load_pem_private_key(pem, password=passphrase.encode("utf-8"))
    except (ValueError, TypeError) as exc:
        raise SystemExit("Cannot unlock the selected vendor private key; check the passphrase and PEM file.") from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise SystemExit("The selected PEM file is not an Ed25519 private key.")
    return key


def generate(machine_id, private_key):
    normalized_machine = normalize_machine_id(machine_id)
    if not normalized_machine:
        raise ValueError("Machine ID is required.")
    license_id = license_number_for(normalized_machine)
    signature = private_key.sign(license_message(normalized_machine, license_id))
    license_key = base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
    return license_id, license_key


def main(argv=None):
    parser = argparse.ArgumentParser(description="Issue a CAESAR POS device-bound license.")
    parser.add_argument("--private-key", default=os.environ.get(PRIVATE_KEY_ENV),
                        help=f"Vendor Ed25519 private PEM path (or set {PRIVATE_KEY_ENV}); never put it in the application/repository.")
    parser.add_argument("--machine-id", help="Customer Machine ID; if omitted, prompt interactively.")
    parser.add_argument("--no-pause", action="store_true",
                        help="Do not pause after displaying the license (for wrapper scripts).")
    args = parser.parse_args(argv)
    if not args.private_key:
        parser.error(f"A vendor private key is required via --private-key or {PRIVATE_KEY_ENV}; no key is embedded or generated.")
    private_key = load_private_key(args.private_key)
    machine_id = args.machine_id if args.machine_id is not None else input("Machine ID: ").strip()
    if not machine_id:
        raise SystemExit("Machine ID is required.")
    license_id, license_key = generate(machine_id, private_key)
    print(f"\nProduct: CAESAR POS\nLicense ID: {license_id}\nLicense Key: {license_key}")
    if sys.stdin.isatty() and not args.no_pause:
        input("\nاضغط Enter للخروج...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
