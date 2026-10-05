"""Encrypted inputs remain untrusted archive/path data after decryption."""
import base64
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from tracecascade.model import ModelError
from tracecascade.secure import _key, backup, restore


PASSWORD = "synthetic " + "test passphrase"


def encrypted_zip(path, entries):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries:
            if isinstance(name, str):
                # Preserve hostile raw ZIP spelling even on Windows, whose
                # ZipInfo constructor otherwise normalizes backslashes.
                info = zipfile.ZipInfo("placeholder")
                info.filename = info.orig_filename = name
                name = info
            archive.writestr(name, content)
    salt, nonce = os.urandom(16), os.urandom(12)
    path.write_text(json.dumps({"version": 1, "algorithm": "AES-256-GCM", "kdf": "scrypt-n16384-r8-p1",
                               "salt": base64.b64encode(salt).decode(), "nonce": base64.b64encode(nonce).decode(),
                               "ciphertext": base64.b64encode(AESGCM(_key(PASSWORD, salt)).encrypt(
                                   nonce, buffer.getvalue(), b"tracecascade-backup-v1")).decode()}))


class RestoreBoundaryTests(unittest.TestCase):
    def test_entry_count_and_expansion_limits_are_preflighted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive, target = root / "archive.enc", root / "target"
            encrypted_zip(archive, [("one", "123"), ("two", "456")])
            for option, limit in (("MAX_BACKUP_FILES", 1), ("MAX_BACKUP_BYTES", 5)):
                with self.subTest(option=option), patch("tracecascade.secure." + option, limit):
                    with self.assertRaises(ModelError):
                        restore(archive, target, PASSWORD)
                    self.assertFalse(target.exists())

    @unittest.skipIf(os.name == "nt", "POSIX symlink regression")
    def test_symlink_source_and_destination_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            actual = root / "actual"
            actual.mkdir()
            link = root / "linked"
            link.symlink_to(actual, target_is_directory=True)
            archive = root / "archive.enc"
            encrypted_zip(archive, [("safe", "content")])
            with self.assertRaises(ModelError):
                restore(archive, link, PASSWORD)
            self.assertEqual(list(actual.iterdir()), [])
            with self.assertRaises(ModelError):
                backup(link, root / "rejected.enc", PASSWORD)
            self.assertFalse((root / "rejected.enc").exists())

    def test_portable_paths_rejected_before_any_target_created(self):
        for name in ("C:/escape", "C:escape", "a\\b", "a//b", "a/./b", "CON.txt", "tail.",
                     "tail ", "file:stream", "a/../b", "control\nname", "wild*card"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                archive, target = root / "archive.enc", root / "target"
                encrypted_zip(archive, [("valid.txt", "safe"), (name, "unsafe")])
                with self.assertRaises(ModelError):
                    restore(archive, target, PASSWORD)
                self.assertFalse(target.exists())

    def test_case_collisions_and_file_parent_conflicts_rejected_in_preflight(self):
        for names in (("File", "file"), ("parent", "parent/child"), ("Dir/a", "dir/b")):
            with self.subTest(names=names), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                archive, target = root / "archive.enc", root / "target"
                encrypted_zip(archive, [(name, "safe") for name in names])
                with self.assertRaises(ModelError):
                    restore(archive, target, PASSWORD)
                self.assertFalse(target.exists())

    def test_archive_link_mode_rejected_before_target_creation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            entry = zipfile.ZipInfo("link")
            entry.create_system = 3
            entry.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive, target = root / "archive.enc", root / "target"
            encrypted_zip(archive, [(entry, "../outside")])
            with self.assertRaises(ModelError):
                restore(archive, target, PASSWORD)
            self.assertFalse(target.exists())

    def test_malformed_envelope_types_return_model_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "archive.enc"
            encrypted_zip(archive, [("safe", "content")])
            original = json.loads(archive.read_text())
            for field, value in (("version", True), ("salt", []), ("nonce", 42), ("ciphertext", {})):
                candidate = dict(original)
                candidate[field] = value
                archive.write_text(json.dumps(candidate))
                with self.subTest(field=field), self.assertRaises(ModelError):
                    restore(archive, root / "target", PASSWORD)

    @unittest.skipUnless(os.name == "nt", "Windows junction regression")
    def test_junction_source_and_destination_rejected_without_touching_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            actual = root / "actual"
            actual.mkdir()
            junction = root / "junction"
            result = subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(actual)], capture_output=True)
            self.assertEqual(result.returncode, 0)
            archive = root / "archive.enc"
            encrypted_zip(archive, [("safe", "content")])
            with self.assertRaises(ModelError):
                restore(archive, junction, PASSWORD)
            self.assertEqual(list(actual.iterdir()), [])
            (actual / "private").write_text("outside data")
            with self.assertRaises(ModelError):
                backup(junction, root / "rejected.enc", PASSWORD)
            self.assertFalse((root / "rejected.enc").exists())
            project = root / "project"
            project.mkdir()
            nested = project / "nested-junction"
            result = subprocess.run(["cmd", "/c", "mklink", "/J", str(nested), str(actual)], capture_output=True)
            self.assertEqual(result.returncode, 0)
            with self.assertRaises(ModelError):
                backup(project, root / "nested-rejected.enc", PASSWORD)
            self.assertFalse((root / "nested-rejected.enc").exists())
