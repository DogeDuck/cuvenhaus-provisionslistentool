"""Regression: Backup errors must not break the local commission database."""
import os
import tempfile
import unittest
from unittest.mock import patch

import autosicherung
import cuvenhaus_suite


class StorageBackupFallbackTests(unittest.TestCase):
    def test_remote_backup_error_keeps_sqlite_usable(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "commissions.sqlite3")
            with patch.object(cuvenhaus_suite, "DB_PATH", db_path):
                with patch.object(autosicherung, "restore_if_missing", return_value=False):
                    with patch.object(autosicherung, "save", side_effect=autosicherung.BackupError("Test-Backup offline")):
                        db = cuvenhaus_suite.Storage()
                        try:
                            db.execute(
                                "INSERT INTO shift_calendar(user_id, friday) VALUES(?,?)",
                                ("driver-test", "2026-10-16"),
                            )
                        finally:
                            db.close()
                        self.assertEqual(db.backup_error, "Test-Backup offline")
            # Data must survive locally even if the remote backup fails.
            with patch.object(cuvenhaus_suite, "DB_PATH", db_path):
                with patch.object(autosicherung, "restore_if_missing", return_value=False):
                    db = cuvenhaus_suite.Storage()
                    try:
                        self.assertEqual(
                            db.execute("SELECT friday FROM shift_calendar WHERE user_id=?",
                                       ("driver-test",)),
                            [("2026-10-16",)],
                        )
                    finally:
                        db.close()

    def test_remote_restore_error_does_not_block_local_create(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "commissions.sqlite3")
            with patch.object(cuvenhaus_suite, "DB_PATH", db_path):
                with patch.object(autosicherung, "restore_if_missing",
                                  side_effect=autosicherung.BackupError("Test Zugriff")):
                    db = cuvenhaus_suite.Storage()
                    try:
                        self.assertEqual(db.backup_error, "Test Zugriff")
                        self.assertEqual(db.execute(
                            "SELECT name FROM sqlite_master WHERE type='table' AND name='shift_calendar'"
                        ), [("shift_calendar",)])
                    finally:
                        db.close()

    def test_older_storage_status_attribute_is_optional(self):
        class CachedLegacyStorage:
            pass

        self.assertEqual(getattr(CachedLegacyStorage(), "backup_error", ""), "")


if __name__ == "__main__":
    unittest.main()
