"""Tests for shared commissions, persisted map coordinates and review decisions."""
import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

import autosicherung
import cuvenhaus_suite
from provi_erweiterungen import (
    claim, unclaim, claims_for, claimants, save_location, get_location,
    validate_coords, audit, decisions, set_decision, prune, get_locations_bulk,
)


class ExtensionsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "test.sqlite3")
        self.path_patch = patch.object(cuvenhaus_suite, "DB_PATH", self.path)
        self.restore_patch = patch.object(autosicherung, "restore_if_missing", return_value=False)
        self.backup_patch = patch.object(autosicherung, "save", return_value=True)
        self.path_patch.start()
        self.restore_patch.start()
        self.backup_patch.start()
        self.db = cuvenhaus_suite.Storage()
        self.db.execute("""CREATE TABLE monthly_orders (
            order_key TEXT PRIMARY KEY, payload TEXT, fingerprint TEXT,
            updated_at TEXT, expires_at TEXT)""")
        self.db.execute("""INSERT INTO monthly_orders VALUES
            ('28255','{}','abc','2026-11-08','2027-01-01')""")

    def tearDown(self):
        self.db.close()
        self.backup_patch.stop()
        self.restore_patch.stop()
        self.path_patch.stop()
        self.tmp.cleanup()

    def test_two_drivers_can_claim_same_job_once_each(self):
        claim(self.db, "Can-Erik Ross", "28255")
        claim(self.db, "Can-Erik Ross", "28255")
        claim(self.db, "Marc Twardy", "28255")
        self.assertEqual(claimants(self.db, "28255"), ["can-erik ross", "marc twardy"])
        self.assertEqual(claims_for(self.db, "CAN-ERIK ROSS"), {"28255"})
        self.assertEqual(claims_for(self.db, "Marc Twardy"), {"28255"})
        unclaim(self.db, "Can-Erik Ross", "28255")
        self.assertEqual(claims_for(self.db, "Can-Erik Ross"), set())
        self.assertEqual(claims_for(self.db, "Marc Twardy"), {"28255"})

    def test_verified_location_survives_reopen(self):
        save_location(self.db, "Bonner Talweg 287", 50.70, 7.10)
        self.assertEqual(get_location(self.db, " BONNER  TALWEG 287 "), (50.7, 7.1))
        self.db.close()
        self.db = cuvenhaus_suite.Storage()
        self.assertEqual(get_location(self.db, "Bonner Talweg 287"), (50.7, 7.1))
        with self.assertRaises(ValueError):
            save_location(self.db, "Bad", float("nan"), 7.0)
        with self.assertRaises(ValueError):
            validate_coords(91, 7.0)

    def test_bulk_locations_match_individual_lookups(self):
        save_location(self.db, "Bonner Talweg 287", 50.70, 7.10)
        save_location(self.db, "Bonn Hauptbahnhof", 50.73, 7.09)
        names = ["Bonner Talweg 287", " BONNER  TALWEG 287 ",
                 "Bonn Hauptbahnhof", "unbekannt", ""]
        result = get_locations_bulk(self.db, names)
        self.assertEqual(result["bonner talweg 287"],
                         get_location(self.db, "Bonner Talweg 287"))
        self.assertEqual(result["bonn hauptbahnhof"],
                         get_location(self.db, "Bonn Hauptbahnhof"))
        self.assertNotIn("unbekannt", result)
        self.assertEqual(get_locations_bulk(self.db, []), {})
        # More than one SQL parameter batch.
        self.assertEqual(len(get_locations_bulk(
            self.db, [f"unknown {i}" for i in range(450)])), 0)

    def test_review_status_persists(self):
        set_decision(self.db, "Can-Erik Ross", "28255", "zone", "Geprüft")
        self.assertEqual(decisions(self.db, "Can-Erik Ross"), {("28255", "zone"): "Geprüft"})
        self.db.close()
        self.db = cuvenhaus_suite.Storage()
        self.assertEqual(decisions(self.db, "Can-Erik Ross"), {("28255", "zone"): "Geprüft"})
        with self.assertRaises(ValueError):
            set_decision(self.db, "Can-Erik Ross", "28255", "zone", "Abgerechnet")

    def test_audit_reports_real_risks_not_manual_overtime(self):
        orders = [
            {"nr": "28255", "betrag": 25, "zone_warning": True, "stat": "abgeschlossen"},
            {"nr": "28256", "betrag": 0, "stat": "abgeschlossen"},
            {"nr": "28257", "betrag": 320, "stat": "abgeschlossen"},
        ]
        result = audit(
            orders, standby_check=lambda o: False,
            manual_ids={"28255"},
            claim_map={"28255": ["marc twardy", "can-erik ross"]},
        )
        issues = {(nr, code) for nr, code, _ in result}
        self.assertIn(("28255", "zone"), issues)
        self.assertIn(("28255", "shared"), issues)
        self.assertNotIn(("28255", "outside"), issues)
        self.assertIn(("28256", "zero"), issues)
        self.assertIn(("28256", "outside"), issues)
        self.assertIn(("28257", "high"), issues)

    def test_cleanup_preserves_active_orders(self):
        claim(self.db, "Can-Erik Ross", "28255")
        claim(self.db, "Can-Erik Ross", "expired")
        set_decision(self.db, "Can-Erik Ross", "expired", "zone", "Ignoriert")
        prune(self.db)
        self.assertEqual(claims_for(self.db, "Can-Erik Ross"), {"28255"})
        self.assertNotIn(("expired", "zone"), decisions(self.db, "Can-Erik Ross"))


if __name__ == "__main__":
    unittest.main()
