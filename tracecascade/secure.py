"""Password-encrypted project backup and safe restore."""

from __future__ import annotations

import base64
import io
import json
import os
import stat
import zipfile
from pathlib import Path, PurePosixPath

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from .model import ModelError, _relative_path
from .report import atomic_text


MAX_BACKUP_BYTES = 100_000_000
MAX_ENVELOPE_BYTES = 140_000_000
MAX_BACKUP_FILES = 100_000


def _archive_name(name: str) -> PurePosixPath:
    try:
        _relative_path(name, "Backup path")
    except ModelError as exc:
        raise ModelError("Backup contains an unsafe path") from exc
    if any(ord(char) < 32 or char in '<>"|?*' for char in name):
        raise ModelError("Backup contains an unsafe path")
    return PurePosixPath(name)


def _preflight_names(names: list[str]) -> None:
    files = set(names)
    seen: dict[str, str] = {}
    for name in names:
        path = _archive_name(name)
        for segment in [path, *list(path.parents)[:-1]]:
            normalized = segment.as_posix()
            folded = normalized.casefold()
            if folded in seen and seen[folded] != normalized:
                raise ModelError("Backup contains case-colliding paths")
            seen[folded] = normalized
        if any(parent.as_posix() in files for parent in list(path.parents)[:-1]):
            raise ModelError("Backup file is also a parent directory")


def _key(password: str, salt: bytes) -> bytes:
    if len(password) < 12:
        raise ModelError("Backup password must be at least 12 characters")
    return Scrypt(salt=salt, length=32, n=2**14, r=8, p=1).derive(password.encode("utf-8"))


def backup(root: Path, output: Path, password: str) -> dict:
    if root.is_symlink() or root.is_junction():
        raise ModelError("Backup refuses a linked project root")
    root, output = root.resolve(), output.resolve()
    if not root.is_dir() or output.is_relative_to(root):
        raise ModelError("Encrypted backup output must be outside the project directory")
    buffer = io.BytesIO()
    total, count = 0, 0
    archived_names = []
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root)
            if any(part in {".git", "build", "dist", "__pycache__"} for part in relative.parts):
                continue
            if path.is_symlink() or path.is_junction():
                raise ModelError(f"Backup refuses symbolic link or junction: {relative}")
            if not path.is_file():
                continue
            _archive_name(relative.as_posix())
            size = path.stat().st_size
            total += size
            count += 1
            if total > MAX_BACKUP_BYTES or count > MAX_BACKUP_FILES:
                raise ModelError(f"Backup exceeds {MAX_BACKUP_BYTES} uncompressed bytes")
            archive.write(path, relative.as_posix())
            archived_names.append(relative.as_posix())
    _preflight_names(archived_names)
    salt, nonce = os.urandom(16), os.urandom(12)
    associated = b"tracecascade-backup-v1"
    ciphertext = AESGCM(_key(password, salt)).encrypt(nonce, buffer.getvalue(), associated)
    envelope = {"version": 1, "algorithm": "AES-256-GCM", "kdf": "scrypt-n16384-r8-p1",
                "salt": base64.b64encode(salt).decode("ascii"), "nonce": base64.b64encode(nonce).decode("ascii"),
                "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
                "files": count, "uncompressed_bytes": total}
    atomic_text(output, json.dumps(envelope, indent=2) + "\n")
    return {"files": count, "uncompressed_bytes": total}


def restore(archive_path: Path, output: Path, password: str) -> dict:
    try:
        if archive_path.stat().st_size > MAX_ENVELOPE_BYTES:
            raise ModelError(f"Encrypted backup exceeds {MAX_ENVELOPE_BYTES} bytes")
        envelope = json.loads(archive_path.read_bytes())
        if (not isinstance(envelope, dict) or type(envelope.get("version")) is not int or envelope.get("version") != 1
                or envelope.get("algorithm") != "AES-256-GCM" or envelope.get("kdf") != "scrypt-n16384-r8-p1"):
            raise ModelError("Unsupported encrypted backup format")
        if any(not isinstance(envelope.get(field), str) for field in ("salt", "nonce", "ciphertext")):
            raise ModelError("Malformed encrypted backup fields")
        salt = base64.b64decode(envelope["salt"], validate=True)
        nonce = base64.b64decode(envelope["nonce"], validate=True)
        ciphertext = base64.b64decode(envelope["ciphertext"], validate=True)
        if len(salt) != 16 or len(nonce) != 12:
            raise ModelError("Malformed encrypted backup salt or nonce")
        plaintext = AESGCM(_key(password, salt)).decrypt(nonce, ciphertext, b"tracecascade-backup-v1")
    except InvalidTag as exc:
        raise ModelError("Backup password is wrong or archive was modified") from exc
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, ValueError) as exc:
        raise ModelError(f"Cannot read encrypted backup: {exc}") from exc
    if output.is_symlink() or output.is_junction():
        raise ModelError("Restore destination must not be a symbolic link or junction")
    output = output.resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ModelError("Restore destination must be an empty directory or not exist")
    restored, total = 0, 0
    try:
        with zipfile.ZipFile(io.BytesIO(plaintext)) as zipped:
            entries: list[tuple[zipfile.ZipInfo, PurePosixPath]] = []
            names: set[str] = set()
            if len(zipped.infolist()) > MAX_BACKUP_FILES:
                raise ModelError("Backup exceeds file count limit")
            for info in zipped.infolist():
                # ZipInfo.filename normalizes backslashes on Windows and
                # truncates NULs. Validate the original unnormalized spelling.
                relative = _archive_name(info.orig_filename)
                mode = stat.S_IFMT(info.external_attr >> 16)
                if info.is_dir() or mode not in (0, stat.S_IFREG):
                    raise ModelError("Backup contains an unsafe path")
                normalized = relative.as_posix()
                if normalized in names:
                    raise ModelError("Backup contains duplicate paths")
                names.add(normalized)
                total += info.file_size
                if total > MAX_BACKUP_BYTES:
                    raise ModelError("Backup expands beyond the restore limit")
                entries.append((info, relative))
            _preflight_names(list(names))
            output.mkdir(parents=True, exist_ok=True)
            for info, relative in entries:
                destination = output.joinpath(*relative.parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                with zipped.open(info) as source, destination.open("xb") as target:
                    written = 0
                    while block := source.read(1024 * 1024):
                        written += len(block)
                        if written > info.file_size:
                            raise ModelError("Backup entry expands beyond its declared size")
                        target.write(block)
                    if written != info.file_size:
                        raise ModelError("Backup entry size does not match its declaration")
                restored += 1
    except (OSError, zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError) as exc:
        raise ModelError(f"Cannot restore encrypted backup: {exc}") from exc
    return {"files": restored, "uncompressed_bytes": total}
