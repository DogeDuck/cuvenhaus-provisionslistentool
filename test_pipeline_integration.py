"""Regression integration: full OnStreet-shaped CSV and standby rules.

All fixture values synthetic: no actual uploaded CSV or customer data is committed.
"""
import ast
import csv
import io
import re
import unittest
from datetime import datetime, date, timedelta
from pathlib import Path


def _load_functions(*names):
    source = Path("ProviProject-WebApp.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    self_contained = ast.Module(body=functions, type_ignores=[])
    env = {
        "csv": csv,
        "re": re,
        "datetime": datetime,
        "timedelta": timedelta,
        "date": date,
        # Stub the independently tested pricing rules, prevent any geocoding/network.
        "match_tariff_rule": lambda *args: ("Testtarif", 25.0),
    }
    exec(compile(self_contained, "ProviProject-WebApp.py", "exec"), env)
    return env


def _csv_bytes(rows):
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, delimiter=";")
    writer.writerow([
        "Aktueller Status", "Auftrag", "Int. Nummer", "Fall",
        "Auftragsart", "Einsatzmittel", "Fahrer", "Disponiert durch",
        "Einsatzort", "Zielort", "Auftraggeber", "Havarist",
        "Fahrzeug", "Kennzeichen", "Annahme",
    ])
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8-sig")


def _row(n, driver="Mitarbeiter Test", status="Auftrag abgeschlossen",
         when="17.10.2026 16:03:11", kind="Abschleppen"):
    return [status, str(n), "", "", kind, "", driver, "",
            "Teststr. 1, Bonn", "Teststr. 2, Bonn", "ADAC e.V.",
            "", "", "TEST-XX", when]


class OnStreetIntegrationTests(unittest.TestCase):
    def test_many_realistic_rows_parse_with_seconds(self):
        env = _load_functions(
            "safe_text", "parse_dt", "find_header_index",
            "cell", "import_csv_bytes",
        )
        rows = [_row(i, driver="Mitarbeiter A" if i % 2 else "Mitarbeiter B") for i in range(1000, 1258)]
        orders, drivers, headers = env["import_csv_bytes"](_csv_bytes(rows))
        self.assertEqual(len(orders), 258)
        self.assertEqual(drivers, ["Mitarbeiter A", "Mitarbeiter B"])
        self.assertEqual(orders["1001"]["dt"], datetime(2026, 10, 17, 16, 3, 11))
        self.assertEqual(orders["1001"]["betrag"], 25.0)
        self.assertEqual(orders["1001"]["start"], "Teststr. 1, Bonn")
        self.assertIn("auftrag", headers)

    def test_import_deduplicates_same_number(self):
        env = _load_functions(
            "safe_text", "parse_dt", "find_header_index", "cell", "import_csv_bytes",
        )
        a = _row(2001)
        b = _row(2001, status="(P) Auftrag abgeschlossen", when="18.10.2026 20:00:00")
        orders, _, _ = env["import_csv_bytes"](_csv_bytes([a, b]))
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders["2001"]["stat"], "(P) Auftrag abgeschlossen")

    def test_standby_boundaries_and_no_auto_weekdays(self):
        env = _load_functions("standby_bounds", "is_in_standby")
        fri = date(2026, 10, 16)
        yes = ["2026-10-16 21:00", "2026-10-17 14:00", "2026-10-18 21:00"]
        no = ["2026-10-16 20:59", "2026-10-18 21:01", "2026-10-19 09:00"]
        for value in yes:
            self.assertTrue(env["is_in_standby"](
                {"dt": datetime.strptime(value, "%Y-%m-%d %H:%M")}, fri), value)
        for value in no:
            self.assertFalse(env["is_in_standby"](
                {"dt": datetime.strptime(value, "%Y-%m-%d %H:%M")}, fri), value)
        source = Path("ProviProject-WebApp.py").read_text(encoding="utf-8")
        self.assertNotIn("is_weekday_commission(", source)



if __name__ == "__main__":
    unittest.main()
