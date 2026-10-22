"""Tests for shared month archive: duplicates, updates, expiry and restore."""
import os
import tempfile
import unittest
from datetime import date
from unittest.mock import patch

import monatsarchiv
import cuvenhaus_suite


class MonthArchiveTests(unittest.TestCase):
    def test_duplicate_update_retention(self):
        with tempfile.TemporaryDirectory() as td:
            old = os.getcwd()
            os.chdir(td)
            try:
                db = monatsarchiv.get_db()
                try:
                    sample = {"nr": "123", "fahrer": "Test Fahrer",
                              "datum": "16.10.2026", "zeit": "22:00",
                              "annahme": "16.10.2026 22:00",
                              "betrag": 25, "stat": "fertig"}
                    self.assertEqual(monatsarchiv.upsert_import(db, [sample], date(2026,10,22))["neu"], 1)
                    self.assertEqual(monatsarchiv.upsert_import(db, [sample], date(2026,10,22))["unveraendert"], 1)
                    changed = {**sample, "betrag": 30}
                    self.assertEqual(monatsarchiv.upsert_import(db, [changed], date(2026,10,22))["aktualisiert"], 1)
                    records = monatsarchiv.load_orders(db)
                    self.assertEqual(len(records), 1)
                    self.assertEqual(records["123"]["betrag"], 30)
                    self.assertEqual(records["123"]["dt"].hour, 22)
                    monatsarchiv.prune(db, date(2027, 2, 1))
                    self.assertEqual(len(monatsarchiv.load_orders(db)), 0)
                finally:
                    db.close()
            finally:
                os.chdir(old)


if __name__ == "__main__":
    unittest.main()
