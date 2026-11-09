import ast
import pathlib
import re
import unittest


def load_pure(name, namespace):
    tree = ast.parse(pathlib.Path("ProviProject-WebApp.py").read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), "<test>", "exec"), namespace)
    return namespace[name]


class OnstreetAddressRegression(unittest.TestCase):
    def test_duplicates(self):
        ns = {"re": re, "safe_text": lambda x: str(x or "")}
        clean = load_pure("collapse_onstreet_repetitions", ns)
        self.assertEqual(clean("Maarstr 48Maarstr 48"), "Maarstr 48")
        self.assertEqual(clean("Römlinghovener Str 68-72bRömlinghovener Str 68-72b"),
                         "Römlinghovener Str 68-72b")
        self.assertEqual(clean("August-Bebel-Allee 6-12August-Bebel-Allee 6-12"),
                         "August-Bebel-Allee 6-12")

    def test_bonn_borough_split(self):
        ns = {
            "re": re, "safe_text": lambda x: str(x or ""),
            "_street_start_index": lambda x: next(
                (i for i, t in enumerate(x.split())
                 if re.search(r"(str|straße|allee|weg|pfad)", t, re.I)), None),
            "smart_city_name": str, "smart_street_name": str,
        }
        split = load_pure("_split_city_and_street_after_postcode", ns)
        self.assertEqual(split("Bonn Beuel Clemensstraße 96"),
                         ("Bonn", "Clemensstraße 96"))
        self.assertEqual(split("Bonn Bad Godesberg Godesberger Allee 57"),
                         ("Bonn", "Godesberger Allee 57"))
        self.assertEqual(split("Bad Godesberg Godesberger Allee 57"),
                         ("Bonn", "Godesberger Allee 57"))
        self.assertEqual(split("Meckenheim Am Wiesenpfad 13"),
                         ("Meckenheim", "Am Wiesenpfad 13"))


if __name__ == "__main__":
    unittest.main()
