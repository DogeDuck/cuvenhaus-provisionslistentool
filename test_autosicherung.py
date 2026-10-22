"""Tests of keyless private-GitHub SQLite backups, with mocked HTTP."""
import base64
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import autosicherung


class BackupTests(unittest.TestCase):
    def test_backup_round_trip_without_encryption_key(self):
        with tempfile.TemporaryDirectory() as td:
            filename = os.path.join(td, "state.sqlite3")
            db = sqlite3.connect(filename)
            db.execute("CREATE TABLE monthly_orders (order_key TEXT)")
            db.execute("CREATE TABLE shift_calendar (user_id TEXT)")
            db.execute("CREATE TABLE billing_history (driver TEXT)")
            db.execute("INSERT INTO monthly_orders VALUES (?)", ("EXAMPLE-123",))
            db.commit()
            remote = {"blob": None}
            def fake_request(repo, token, endpoint, method="GET", payload=None):
                if endpoint == "":
                    return {"private": True}
                if method == "PUT":
                    remote["blob"] = payload["content"]
                    return {"content": {"sha": "fake"}}
                if endpoint.startswith("/contents/") and remote["blob"]:
                    return {
                        "encoding": "base64", "sha": "fake",
                        "content": remote["blob"],
                    }
                return None

            with patch.object(autosicherung, "config", return_value=("owner/private", "token")):
                with patch.object(autosicherung, "_request", side_effect=fake_request):
                    self.assertTrue(autosicherung.save(db))
                    self.assertTrue(remote["blob"])
                    packed = base64.b64decode(remote["blob"])
                    self.assertEqual(autosicherung._decode(packed)[:16], b"SQLite format 3\0")
                    db.close()
                    os.unlink(filename)
                    self.assertTrue(autosicherung.restore_if_missing(filename))
                    with sqlite3.connect(filename) as restored:
                        self.assertEqual(
                            restored.execute("SELECT order_key FROM monthly_orders").fetchone(),
                            ("EXAMPLE-123",),
                        )

    def test_private_repo_is_required(self):
        with patch.object(autosicherung, "_request", return_value={"private": False}):
            with self.assertRaises(autosicherung.BackupError):
                autosicherung._repo_info("owner/public", "token")

    def test_corrupt_checksum_is_rejected(self):
        raw = b"SQLite format 3\0" + b"x" * 5000
        packed = bytearray(autosicherung._encode(raw))
        packed[len(autosicherung.MAGIC)] ^= 1
        with self.assertRaisesRegex(autosicherung.BackupError, "Prüfsumme"):
            autosicherung._decode(bytes(packed))

    def test_keyless_config(self):
        with patch.dict(os.environ, {
            "GITHUB_BACKUP_REPO": "owner/private",
            "GITHUB_BACKUP_TOKEN": "test-token",
            "BACKUP_ENCRYPTION_KEY": "unused-old-key",
        }):
            self.assertEqual(autosicherung.config(), ("owner/private", "test-token"))

    def test_incomplete_config_rejected(self):
        with patch.dict(os.environ, {
            "GITHUB_BACKUP_REPO": "owner/private",
            "GITHUB_BACKUP_TOKEN": "",
        }):
            with self.assertRaises(autosicherung.BackupError):
                autosicherung.config()


if __name__ == "__main__":
    unittest.main()
