import unittest

from strassenkilometer import parse_road_reference


class RoadReferenceTests(unittest.TestCase):
    def test_repeated_onstreet_reference(self):
        result = parse_road_reference(
            "53113 Bonn B42-5 1.5-1.8 B42-5 1.5-1.8, 53113 Bonn"
        )
        self.assertEqual(result["road"], "B42")
        self.assertEqual(result["section"], "5")
        self.assertEqual((result["km_start"], result["km_end"]), (1.5, 1.8))

    def test_comma_decimal(self):
        self.assertEqual(parse_road_reference("A59-2 10,2-10,8")["road"], "A59")

    def test_normal_addresses_are_untouched(self):
        self.assertIsNone(parse_road_reference("Koblenzer Str 165, 53177 Bonn"))
        self.assertIsNone(parse_road_reference("Bonner Talweg 287, Bonn"))

    def test_reject_invalid_ranges(self):
        self.assertIsNone(parse_road_reference("B42-5 4.2-1.5"))
        self.assertIsNone(parse_road_reference("B42-5 1.5-40.0"))


if __name__ == "__main__":
    unittest.main()
