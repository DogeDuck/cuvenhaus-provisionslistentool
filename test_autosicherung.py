"""Mocked tests: encrypted backups never contact real GitHub."""
import base64
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from cryptography.fernet import Fernet
import autosicherung


class BackupTests(unittest.TestCase):
    def test_encrypted_round_trip(self):
        with tempfile.TemporaryDirectory() as td:
            filename = os.path.join(td, "state.sqlite3")
            db = sqlite3.connect(filename)
            db.execute("CREATE TABLE monthly_orders (order_key TEXT)")
            db.execute("CREATE TABLE shift_calendar (user_id TEXT)")
            db.execute("CREATE TABLE billing_history (driver TEXT)")
            db.execute("INSERT INTO monthly_orders VALUES (?)", ("EXAMPLE-SENSITIVE-123",))
            db.commit()
            key = Fernet.generate_key().decode("ascii")
            remote = {"blob": None}
            def fake_request(repo, token, endpoint, method="GET", payload=None):
                if endpoint == "":
                    return {"private": True}
                if method == "PUT":
                    remote["blob"] = payload["content"]
                    return {"content": {"sha": "fake"}}
                if endpoint.startswith("/contents/") and remote["blob"]:
                    return {"encoding": "base64", "sha": "fake",
                            "content": remote["blob"]}
                return None

            with patch.object(autosicherung, "config", return_value=("owner/private", "token", key)):
                with patch.object(autosicherung, "_request", side_effect=fake_request):
                    self.assertTrue(autosicherung.save(db))
                    self.assertNotIn("EXAMPLE-SENSITIVE-123", remote["blob"])
                    db.close()
                    os.unlink(filename)
                    self.assertTrue(autosicherung.restore_if_missing(filename))
                    restored = sqlite3.connect(filename)
                    self.assertEqual(restored.execute("SELECT order_key FROM monthly_orders").fetchone(),
                                     ("EXAMPLE-SENSITIVE-123",))
                    restored.close()

    def test_public_repository_is_rejected(self):
        with patch.object(autosicherung, "_request", return_value={"private": False}):
            with self.assertRaises(autosicherung.BackupError):
                autosicherung._repo_info("owner/public", "token")

    def test_wrong_decryption_key_is_rejected(self):
        first_key = Fernet.generate_key().decode("ascii")
        wrong_key = Fernet.generate_key().decode("ascii")
        ciphertext = Fernet(first_key.encode()).encrypt(b"secret")
        with self.assertRaises(autosicherung.BackupError):
            autosicherung._decode(ciphertext, wrong_key)


if __name__ == "__main__":
    unittest.main()
