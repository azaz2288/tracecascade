"""Password-encrypted project backup and safe restore."""

from __future__ import annotations

import base64
import io
import json
import os
import zipfile
from pathlib import Path, PurePosixPath

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from .model import ModelError
from .report import atomic_text


MAX_BACKUP_BYTES = 100_000_000
MAX_ENVELOPE_BYTES = 140_000_000


def _key(password: str, salt: bytes) -> bytes:
    if len(password) < 12:
        raise ModelError("Backup password must be at least 12 characters")
    return Scrypt(salt=salt, length=32, n=2**14, r=8, p=1).derive(password.encode("utf-8"))


def backup(root: Path, output: Path, password: str) -> dict:
    root, output = root.resolve(), output.resolve()
    if not root.is_dir() or output.is_relative_to(root):
        raise ModelError("Encrypted backup output must be outside the project directory")
    buffer = io.BytesIO()
    total, count = 0, 0
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root)
            if any(part in {".git", "build", "dist", "__pycache__"} for part in relative.parts):
                continue
            if path.is_symlink():
                raise ModelError(f"Backup refuses symbolic link: {relative}")
            if not path.is_file():
                continue
            size = path.stat().st_size
            total += size
            count += 1
            if total > MAX_BACKUP_BYTES:
                raise ModelError(f"Backup exceeds {MAX_BACKUP_BYTES} uncompressed bytes")
            archive.write(path, relative.as_posix())
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
        if (not isinstance(envelope, dict) or envelope.get("version") != 1
                or envelope.get("algorithm") != "AES-256-GCM" or envelope.get("kdf") != "scrypt-n16384-r8-p1"):
            raise ModelError("Unsupported encrypted backup format")
        salt = base64.b64decode(envelope["salt"], validate=True)
        nonce = base64.b64decode(envelope["nonce"], validate=True)
        ciphertext = base64.b64decode(envelope["ciphertext"], validate=True)
        plaintext = AESGCM(_key(password, salt)).decrypt(nonce, ciphertext, b"tracecascade-backup-v1")
    except InvalidTag as exc:
        raise ModelError("Backup password is wrong or archive was modified") from exc
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, ValueError) as exc:
        raise ModelError(f"Cannot read encrypted backup: {exc}") from exc
    output = output.resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ModelError("Restore destination must be an empty directory or not exist")
    restored, total = 0, 0
    try:
        with zipfile.ZipFile(io.BytesIO(plaintext)) as zipped:
            entries: list[tuple[zipfile.ZipInfo, PurePosixPath]] = []
            names: set[str] = set()
            for info in zipped.infolist():
                relative = PurePosixPath(info.filename)
                if relative.is_absolute() or any(part in ("", ".", "..") for part in relative.parts) or info.is_dir():
                    raise ModelError("Backup contains an unsafe path")
                normalized = relative.as_posix()
                if normalized in names:
                    raise ModelError("Backup contains duplicate paths")
                names.add(normalized)
                total += info.file_size
                if total > MAX_BACKUP_BYTES:
                    raise ModelError("Backup expands beyond the restore limit")
                entries.append((info, relative))
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
    except (OSError, zipfile.BadZipFile) as exc:
        raise ModelError(f"Cannot restore encrypted backup: {exc}") from exc
    return {"files": restored, "uncompressed_bytes": total}
