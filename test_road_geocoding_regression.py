import ast
import pathlib
import unittest

from strassenkilometer import parse_road_identifier


class RoadGeocodingRegressionTests(unittest.TestCase):
    def test_l158_is_road_not_bonn_centre(self):
        ref = parse_road_identifier("Bonn L158 L158, Bonn")
        self.assertEqual(ref["road"], "L158")
        self.assertIsNone(ref["km_start"])
        self.assertIsNone(ref["km_end"])

    def test_road_kilometre_still_works(self):
        ref = parse_road_identifier("B42-5 1.5-1.8")
        self.assertEqual(ref["road"], "B42")
        self.assertEqual(ref["section"], "5")

    def test_street_name_not_road_number(self):
        self.assertIsNone(parse_road_identifier("Am Wiesenpfad 13, 53340 Meckenheim"))

    def test_address_split_meckenheim(self):
        # Execute only pure address-cleaner helpers, without Streamlit side effects.
        source = pathlib.Path("ProviProject-WebApp.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        fn = next(node for node in tree.body
                  if isinstance(node, ast.FunctionDef)
                  and node.name == "_split_city_and_street_after_postcode")
        import re
        ns = {
            "re": re,
            "safe_text": lambda value: str(value or ""),
            "_street_start_index": lambda value: next(
                (i for i, token in enumerate(value.split())
                 if re.search(r"(?:pfad|straße|strasse|weg)$", token, re.I)),
                None),
            "smart_city_name": lambda value: value,
            "smart_street_name": lambda value: value,
        }
        exec(compile(ast.Module(body=[fn], type_ignores=[]),
                     "<address-cleaner>", "exec"), ns)
        city, street = ns["_split_city_and_street_after_postcode"](
            "Meckenheim Am Wiesenpfad 13")
        self.assertEqual(city, "Meckenheim")
        self.assertEqual(street, "Am Wiesenpfad 13")


if __name__ == "__main__":
    unittest.main()
