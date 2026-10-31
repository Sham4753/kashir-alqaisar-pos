#!/usr/bin/env python3
"""Create vendor Ed25519 keys once; private output must stay outside this repository."""
import argparse
from getpass import getpass
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PUBLIC_PATH = REPO_ROOT / "app" / "license_public_key.pem"


def is_within(path, parent):
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def write_exclusive(path, content, mode):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def main(argv=None):
    parser = argparse.ArgumentParser(description="Create the CAESAR POS vendor signing key pair (one time only).")
    parser.add_argument("--private-key-path", required=True,
                        help="Absolute or relative path OUTSIDE this repository for the private PEM.")
    parser.add_argument("--public-key-path", default=str(DEFAULT_PUBLIC_PATH),
                        help="Public PEM destination (safe to publish; defaults to app/license_public_key.pem).")
    args = parser.parse_args(argv)

    private_path = Path(args.private_key_path).expanduser().resolve()
    public_path = Path(args.public_key_path).expanduser().resolve()
    if is_within(private_path, REPO_ROOT):
        parser.error("The private key path must be outside the repository.")
    if private_path == public_path:
        parser.error("Private and public key paths must be different.")
    if private_path.exists() or public_path.exists():
        parser.error("Refusing to overwrite an existing key file; back up and inspect paths manually.")
    if is_within(public_path, private_path):
        parser.error("The public key must not be written inside the private-key directory.")

    passphrase = getpass("Create a passphrase for the vendor private key (minimum 12 characters): ")
    if len(passphrase) < 12:
        parser.error("The private-key passphrase must be at least 12 characters.")
    if getpass("Repeat the private-key passphrase: ") != passphrase:
        parser.error("The passphrases do not match; no key files were written.")

    private_key = Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.BestAvailableEncryption(passphrase.encode("utf-8")),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    try:
        write_exclusive(private_path, private_pem, 0o600)
        write_exclusive(public_path, public_pem, 0o644)
    except OSError as exc:
        # Never remove or overwrite user files on failure; the caller can safely resolve a partial write.
        raise SystemExit(f"Could not create key files: {exc}. Check both paths before retrying.") from exc

    print(f"Public verification key written: {public_path}")
    print(f"Private signing key written outside the repository: {private_path}")
    print("The private key is encrypted. Back up the file and passphrase separately; never copy either into a client package.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
