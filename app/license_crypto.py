"""Offline Ed25519 license verification for CAESAR POS.

The application intentionally contains no signing capability or private key.
"""
import base64
import hashlib
import json
import re
from pathlib import Path

from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

PRODUCT_ID = "CAESAR POS"
LICENSE_ALGORITHM = "Ed25519"
PUBLIC_KEY_PATH = Path(__file__).resolve().with_name("license_public_key.pem")


def normalize_machine_id(value):
    return re.sub(r"[^A-Za-z0-9:_-]", "", str(value or "").strip()).upper()


def license_number_for(machine_id):
    normalized = normalize_machine_id(machine_id)
    return "CAESAR-" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12].upper()


def license_message(machine_id, license_id):
    """Return canonical signed bytes binding product, machine and license ID."""
    normalized_machine = normalize_machine_id(machine_id)
    normalized_license = str(license_id or "").strip().upper()
    document = {
        "product": PRODUCT_ID,
        "machine_id": normalized_machine,
        "license_id": normalized_license,
    }
    return json.dumps(document, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")


def public_key_path():
    """Use the fixed product trust anchor; it cannot be redirected by environment variables."""
    return PUBLIC_KEY_PATH


def load_public_key(path=None):
    """Load a PEM public key; missing, malformed or non-Ed25519 keys fail closed."""
    try:
        pem = Path(path or public_key_path()).read_bytes()
        key = serialization.load_pem_public_key(pem)
        return key if isinstance(key, Ed25519PublicKey) else None
    except (OSError, ValueError, TypeError, UnsupportedAlgorithm):
        return None


def verify_license_signature(machine_id, license_id, license_key, public_key_file=None):
    """Verify the base64url Ed25519 signature; no private material is read here."""
    normalized_machine = normalize_machine_id(machine_id)
    normalized_license = str(license_id or "").strip().upper()
    signature_text = str(license_key or "").strip()
    if not normalized_machine or normalized_license != license_number_for(normalized_machine):
        return False
    if not signature_text or len(signature_text) > 128:
        return False
    # Accept the single unpadded base64url representation emitted by the vendor tool.
    if not re.fullmatch(r"[A-Za-z0-9_-]{86}", signature_text):
        return False
    try:
        signature = base64.urlsafe_b64decode(signature_text + "==")
        if len(signature) != 64:
            return False
        key = load_public_key(public_key_file)
        if key is None:
            return False
        key.verify(signature, license_message(normalized_machine, normalized_license))
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False
