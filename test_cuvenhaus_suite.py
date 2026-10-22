"""Regressionstests für Cuvenhaus Manager 2.0, ohne personenbezogene Echt-Daten."""
import os
import tempfile
import unittest
from unittest.mock import patch

import cuvenhaus_suite as suite
from datetime import date


class SuiteTests(unittest.TestCase):
    def test_friday_selection(self):
        self.assertEqual(suite.friday_for(date(2026, 10, 18)), date(2026, 10, 16))
        self.assertEqual(suite.friday_for(date(2026, 10, 16)), date(2026, 10, 16))

    def test_review_detects_unusual_values(self):
        orders = [
            {"nr": "a", "betrag": -2, "stat": "Fertig"},
            {"nr": "a", "betrag": 0, "stat": "Fertig", "zone_warning": True},
            {"nr": "b", "betrag": 40, "stat": "Fertig"},
        ]
        findings = suite.review(orders)
        self.assertEqual(len(findings), 2)
        self.assertIn("Doppelte", findings[1]["Hinweise"])
        self.assertIn("FP-Zone", findings[1]["Hinweise"])

    def test_signature_does_not_expose_number(self):
        with patch.object(suite, "setting", return_value="secret" * 8):
            signatures = suite.signatures([{"nr": "SENSITIVE-123", "betrag": 25}])
        self.assertEqual(len(signatures), 1)
        self.assertNotIn("SENSITIVE-123", str(signatures))

    def test_sqlite_calendar_and_history_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            original = os.getcwd()
            os.chdir(directory)
            try:
                with patch.object(suite, "database_url", return_value=""):
                    db = suite.Storage()
                    try:
                        db.execute("INSERT INTO shift_calendar(user_id,friday) VALUES(?,?)", ("test@example.org", "2026-10-16"))
                        self.assertEqual(db.execute("SELECT friday FROM shift_calendar WHERE user_id=?", ("test@example.org",)), [("2026-10-16",)])
                        db.execute("INSERT INTO billing_history(user_id,source_hash,driver,period,count,total,saved_at) VALUES(?,?,?,?,?,?,?)", ("test@example.org", "hash", "driver", "2026-10-16", 2, 55.0, "now"))
                        self.assertEqual(db.execute("SELECT total FROM billing_history WHERE user_id=?", ("test@example.org",)), [(55.0,)])
                    finally:
                        db.close()
            finally:
                os.chdir(original)


if __name__ == "__main__":
    unittest.main()
