"""Regression: no carry-over between weekend commission lists.

Synthetic order numbers and dates only. Nothing from real OnStreet exports.
"""
import unittest
from datetime import date, datetime

from wochenlisten import (
    available_weekends, billing_week_bounds, friday_of_week,
    get_scope, in_billing_week, other_manual_weekend,
)


class WeekendListsTests(unittest.TestCase):
    def test_available_weekends_are_distinct_and_recent_first(self):
        orders = [
            {"dt": datetime(2026, 10, 12, 8, 0), "nr": "A"},
            {"dt": datetime(2026, 10, 17, 12, 0), "nr": "B"},
            {"dt": datetime(2026, 10, 25, 18, 0), "nr": "C"},
            {"dt": datetime(2026, 11, 2, 17, 39), "nr": "D"},
            {"dt": None, "nr": "unknown"},
        ]
        self.assertEqual(
            available_weekends(orders),
            [date(2026, 11, 6), date(2026, 10, 23), date(2026, 10, 16)],
        )

    def test_each_billing_week_excludes_earlier_weekends(self):
        older = date(2026, 10, 16)
        current = date(2026, 10, 23)
        data = [
            ("old_weekend", datetime(2026, 10, 17, 14, 0)),
            ("old_sunday", datetime(2026, 10, 18, 20, 59)),
            ("current_monday", datetime(2026, 10, 19, 8, 0)),
            ("manual_overtime", datetime(2026, 10, 19, 17, 39)),
            ("current_friday", datetime(2026, 10, 23, 21, 0)),
            ("current_sunday", datetime(2026, 10, 25, 23, 59)),
            ("next_monday", datetime(2026, 10, 26, 0, 0)),
        ]
        orders = [{"nr": key, "dt": when} for key, when in data]
        selected = [o["nr"] for o in orders if in_billing_week(o, current)]
        self.assertEqual(
            selected,
            ["current_monday", "manual_overtime", "current_friday", "current_sunday"],
        )
        self.assertTrue(in_billing_week(orders[0], older))
        self.assertFalse(in_billing_week(orders[0], current))
        self.assertEqual(
            billing_week_bounds(current),
            (datetime(2026, 10, 19), datetime(2026, 10, 26)),
        )

    def test_driver_and_weekend_selections_do_not_leak(self):
        states = {}
        older_key, older = get_scope(states, "Testfahrer", date(2026, 10, 16))
        older["manual_added"].update({"old_manual", "old_auto"})
        older["removed_orders"].add("old_auto")
        older["manual_tariffs"]["old_manual"] = {"betrag": 50.0}
        current_key, current = get_scope(states, "Testfahrer", date(2026, 10, 23))
        self.assertNotEqual(older_key, current_key)
        self.assertEqual(current["manual_added"], set())
        self.assertEqual(current["removed_orders"], set())
        self.assertEqual(current["manual_tariffs"], {})
        current["manual_added"].add("current_manual")
        self.assertEqual(older["manual_added"], {"old_manual", "old_auto"})
        _, other_driver = get_scope(states, "Andere Fahrerin", date(2026, 10, 23))
        self.assertEqual(other_driver["manual_added"], set())
        _, revisit = get_scope(states, "Testfahrer", date(2026, 10, 16))
        self.assertIs(revisit, older)

    def test_double_manual_assignment_across_weekends_is_blocked(self):
        scopes = {}
        older_friday = date(2026, 10, 16)
        current_friday = date(2026, 10, 23)
        _, older = get_scope(scopes, "Testfahrer", older_friday)
        older["manual_added"].add("5555")
        self.assertEqual(
            other_manual_weekend(scopes, "Testfahrer", current_friday, "5555"),
            older_friday,
        )
        older["removed_orders"].add("5555")
        self.assertIsNone(other_manual_weekend(scopes, "Testfahrer", current_friday, "5555"))
        self.assertIsNone(other_manual_weekend(scopes, "Andere Fahrerin", current_friday, "5555"))

    def test_midweek_friday_mapping(self):
        self.assertEqual(friday_of_week(date(2026, 11, 2)), date(2026, 11, 6))
        self.assertEqual(friday_of_week(date(2026, 11, 8)), date(2026, 11, 6))


if __name__ == "__main__":
    unittest.main()
