import sqlite3
import unittest
from datetime import date

from csv_versionsvergleich import compare_versions, duplicate_ids, duplicate_csv_numbers
from provisions_waechter import import_alerts, price_alert
from bereitschaftskalender import (assign, unassign, assignments, overlaps, friday_for)
from strassenkilometer import parse_road_reference


class NewFeatureTests(unittest.TestCase):
    def test_csv_diff_ignores_calculated_tariff(self):
        old = {"10": {"nr": "10", "fahrer": "Marc", "start": "Bonn",
                      "betrag": 25, "tarif": "ADAC FP 1"}}
        new = {"10": {"nr": "10", "fahrer": "Marc", "start": "Bonn",
                      "betrag": 30, "tarif": "ADAC FP 2"}}
        self.assertEqual(compare_versions(old, new)["geaendert"], {})
        new["10"]["start"] = "Wachtberg"
        self.assertEqual(compare_versions(old, new)["geaendert"]["10"]["start"],
                         ("Bonn", "Wachtberg"))
        self.assertEqual(old["10"]["start"], "Bonn")

    def test_partial_csv_not_deletion(self):
        diff = compare_versions({"1": {"nr": "1"}}, {})
        self.assertEqual(diff["fehlt_im_export"], ["1"])
        self.assertIn("nicht gelöscht", import_alerts([], diff)[0][2])

    def test_csv_duplicate_detection_before_import(self):
        data = ("Auftrag;Fahrer;Einsatzort\\n"
                "28255;Marc;Bonn\\n"
                "28255;Can-Erik;Bonn\\n"
                "28256;Marc;Wachtberg\\n").encode("utf-8")
        self.assertEqual(duplicate_csv_numbers(data), ["28255"])

    def test_duplicate_and_price_alerts(self):
        self.assertEqual(duplicate_ids([{"nr": "3"}, {"nr": "3"}, {"nr": "4"}]), ["3"])
        self.assertIsNotNone(price_alert(
            {"nr": "3", "final_zone": "FP 2", "betrag": 25, "tarif": "ADAC FP 1"},
            {"FP 2": 30}))
        self.assertIsNone(price_alert(
            {"nr": "3", "final_zone": "FP 2", "betrag": 25, "tarif": "ADAC FP 1"},
            {"FP 2": 30}, manual_override=True))
        self.assertIsNone(price_alert(
            {"nr": "3", "final_zone": "FP 2", "betrag": 0, "tarif": "Storno (0 €)"},
            {"FP 2": 30}))

    def test_standby_calendar_persistence(self):
        db = sqlite3.connect(":memory:")
        try:
            friday = assign(db, date(2026, 11, 7), "Can-Erik", "WE")
            self.assertEqual(friday, "2026-11-06")
            assign(db, date(2026, 11, 6), "Sebastian")
            self.assertEqual(len(assignments(db)), 2)
            self.assertIn("2026-11-06", overlaps(assignments(db)))
            unassign(db, date(2026, 11, 6), "Sebastian")
            self.assertEqual(overlaps(assignments(db)), {})
            self.assertEqual(friday_for(date(2026, 11, 9)), date(2026, 11, 13))
        finally:
            db.close()

    def test_road_km_no_guess(self):
        road = parse_road_reference("53113 Bonn B42-5 1.5-1.8 B42-5 1.5-1.8")
        self.assertEqual((road["road"], road["section"]), ("B42", "5"))
        self.assertEqual((road["km_start"], road["km_end"]), (1.5, 1.8))
        self.assertIsNone(parse_road_reference("Zwischen den Hüllen 47, Wachtberg"))


if __name__ == "__main__":
    unittest.main()
