"""Smoke test: Streamlit must show access gate before any CSV data."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest


class StreamlitStartupTests(unittest.TestCase):
    def test_password_screen_is_first(self):
        source = Path("ProviProject-WebApp.py").resolve()
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {
                "INTERNAL_ACCESS_PIN": "nonproduction-test-only",
                "CUVENHAUS_SQLITE_PATH": os.path.join(tmp, "test.sqlite3"),
            }):
                app = AppTest.from_file(str(source), default_timeout=30).run()
                self.assertFalse(app.exception, [str(item) for item in app.exception])
                self.assertTrue(
                    any("Interner Zugang" in str(item.value) for item in app.title),
                    "Passwortschirm nicht sichtbar",
                )
                self.assertTrue(
                    any("Firmen-Nummer" in str(item.value) for item in app.caption),
                    "Passwort-Hinweis fehlt",
                )


if __name__ == "__main__":
    unittest.main()
