#!/usr/bin/env python3
"""Build a safe, manual CAESAR POS Windows update ZIP from OneFolder output."""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
from pathlib import Path, PurePosixPath

from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

TOOLS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TOOLS_DIR.parent
UPDATER_FILES = {
    "Apply_CAESAR_Update.ps1": TOOLS_DIR / "Apply_CAESAR_Update.ps1",
    "Apply_CAESAR_Update.bat": TOOLS_DIR / "Apply_CAESAR_Update.bat",
    "README_UPDATE_AR.txt": TOOLS_DIR / "README_UPDATE_AR.txt",
}
BLOCKED_DIRS = {
    ".git",
    "__pycache__",
    "vault",
    "license",
    "licenses",
    "logs",
    "log",
    "database",
    "databases",
    "db",
    "sqlite",
    "sqlite3",
    "backup",
    "backups",
    "data",
}
BLOCKED_SUFFIXES = {
    ".json",
    ".json5",
    ".jsonc",
    ".jsonl",
    ".ndjson",
    ".csv",
    ".tsv",
    ".db",
    ".sqlite",
    ".sqlite3",
    ".log",
    ".bak",
    ".key",
    ".pem",
    ".p12",
    ".pfx",
    ".p7b",
    ".p7c",
    ".env",
    ".lic",
    ".license",
    ".licence",
}
SAFE_STATIC_APP_PATHS = {
    ("app", "factory_data.json"),
    ("_internal", "app", "factory_data.json"),
    ("runtime", "_internal", "app", "factory_data.json"),
    ("app", "license_public_key.pem"),
    ("_internal", "app", "license_public_key.pem"),
    ("runtime", "_internal", "app", "license_public_key.pem"),
    ("pythonnet", "runtime", "python.runtime.deps.json"),
    ("_internal", "pythonnet", "runtime", "python.runtime.deps.json"),
    ("runtime", "_internal", "pythonnet", "runtime", "python.runtime.deps.json"),
}


class PackageError(ValueError):
    """Raised when the input OneFolder or package configuration is unsafe."""


def validate_onefolder(folder: Path) -> Path:
    folder = folder.expanduser().resolve()
    if not folder.is_dir():
        raise PackageError(f"OneFolder directory does not exist: {folder}")
    if not (folder / "CAESAR_POS.exe").is_file():
        raise PackageError("Invalid OneFolder: CAESAR_POS.exe is missing.")
    if not any((folder / item).is_dir() for item in ("app", "_internal", "runtime/_internal")):
        raise PackageError("Invalid OneFolder: expected an app, _internal, or runtime/_internal directory.")
    return folder


def _is_vendor_license_metadata(parts: tuple[str, ...]) -> bool:
    """Allow canonical notices under dist-info in known PyInstaller package roots."""
    allowed_prefixes = {
        ("app", "vendor"),
        ("_internal",),
        ("_internal", "app", "vendor"),
        ("runtime", "_internal"),
        ("runtime", "_internal", "app", "vendor"),
    }
    allowed_names = {"license", "license.txt", "notice", "notice.txt", "copying", "copying.txt"}
    for index in range(1, len(parts) - 1):
        if not parts[index].endswith(".dist-info") or parts[:index] not in allowed_prefixes:
            continue
        tail = parts[index + 1:]
        if tail == (parts[-1],) and parts[-1] in allowed_names:
            return True
        if len(tail) == 2 and tail[0] in {"license", "licenses"} and tail[1] in allowed_names:
            return True
    return False


def is_sensitive_or_nonpayload(relative: PurePosixPath) -> bool:
    """Deny customer/runtime data; allow exact static assets and vendored third-party notices."""
    parts = tuple(part.casefold() for part in relative.parts)
    name = parts[-1]
    if _is_vendor_license_metadata(parts):
        return False
    if parts in SAFE_STATIC_APP_PATHS:
        return False
    if any(part in BLOCKED_DIRS for part in parts):
        return True
    if any("secret" in part or "vault" in part for part in parts):
        return True
    if any(re.search(r"(^|[._-])data([._-]|$)", part) for part in parts):
        return True
    if any("license" in part for part in parts[:-1]):
        return True
    if name == "generate_license.py":
        return True
    suffix = PurePosixPath(name).suffix.casefold()
    if suffix in BLOCKED_SUFFIXES:
        return True
    if "license" in name and suffix == ".txt":
        return True
    if name in {".license", "license", "license.secret", ".license_secret"}:
        return True
    if re.search(r"\.(?:sqlite|sqlite3|db)(?:[-.](?:wal|shm|journal))?(?:\.|$)", name):
        return True
    if re.search(r"\.log(?:\.|$)", name):
        return True
    return False


def collect_payload(source: Path) -> tuple[list[tuple[Path, PurePosixPath]], list[PurePosixPath]]:
    included: list[tuple[Path, PurePosixPath]] = []
    excluded: list[PurePosixPath] = []
    for path in sorted(source.rglob("*")):
        relative = PurePosixPath(path.relative_to(source).as_posix())
        if path.is_symlink():
            raise PackageError(f"Symbolic links are not allowed in OneFolder: {relative}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise PackageError(f"Unsupported non-regular file in OneFolder: {relative}")
        parts = tuple(part.casefold() for part in relative.parts)
        if parts in SAFE_STATIC_APP_PATHS and parts[-1] == "license_public_key.pem":
            try:
                public_key = serialization.load_pem_public_key(path.read_bytes())
            except (ValueError, TypeError, UnsupportedAlgorithm) as error:
                raise PackageError(f"Public-key asset is invalid: {relative}") from error
            if not isinstance(public_key, Ed25519PublicKey):
                raise PackageError(f"Public-key asset must be Ed25519: {relative}")
        if is_sensitive_or_nonpayload(relative):
            excluded.append(relative)
            continue
        included.append((path, relative))
    if not any(str(relative).casefold() == "caesar_pos.exe" for _, relative in included):
        raise PackageError("The executable was filtered; refusing to create an unusable update.")
    if not included:
        raise PackageError("OneFolder contains no packageable files.")
    return included, excluded


def build_package(source: Path, output: Path, version: str) -> tuple[int, int]:
    source = validate_onefolder(source)
    output = output.expanduser().resolve()
    if output == source or source in output.parents:
        raise PackageError("The ZIP output must be outside the OneFolder source directory.")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", version):
        raise PackageError("Version must contain only letters, digits, dot, underscore, or hyphen.")
    missing = [str(path) for path in UPDATER_FILES.values() if not path.is_file()]
    if missing:
        raise PackageError("Updater companion file(s) missing: " + ", ".join(missing))

    included, excluded = collect_payload(source)
    package_root = f"CAESAR_POS_Update_{version}"
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for archive_name, file_path in UPDATER_FILES.items():
            archive.write(file_path, f"{package_root}/{archive_name}")
        for local_path, relative in included:
            archive.write(local_path, f"{package_root}/payload/CAESAR_POS/{relative.as_posix()}")

    return len(included), len(excluded)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create a manual Windows update ZIP from a CAESAR POS OneFolder output."
    )
    parser.add_argument("--source", required=True, type=Path, help="Path to dist/CAESAR_POS")
    parser.add_argument("--version", required=True, help="Release label used in the ZIP filename")
    parser.add_argument("--output", type=Path, help="Output ZIP (default: current directory)")
    args = parser.parse_args(argv)
    output = args.output or Path.cwd() / f"CAESAR_POS_Update_{args.version}.zip"
    try:
        included, excluded = build_package(args.source, output, args.version)
    except (PackageError, OSError, zipfile.BadZipFile) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print(f"Created: {output.resolve()}")
    print(f"Program files included: {included}; sensitive/non-payload files excluded: {excluded}")
    print("Inspect the ZIP contents before publishing. It contains no preconfigured license or customer data.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
