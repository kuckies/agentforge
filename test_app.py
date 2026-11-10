import unittest
import os
from tempfile import TemporaryDirectory
from unittest.mock import patch
from pathlib import Path
from streamlit.testing.v1 import AppTest


class InterfaceTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        env = patch.dict(os.environ, {"AGENTFORGE_DB_PATH": str(Path(temp.name) / "test.sqlite3")})
        env.start()
        self.addCleanup(env.stop)

    def test_run_and_validation(self):
        app = AppTest.from_file(str(Path(__file__).with_name("app.py"))).run(timeout=30)
        self.assertFalse(app.exception)
        app.button[0].click().run(timeout=30)
        self.assertFalse(app.exception)
        self.assertEqual(app.metric[0].value, "3 / 3")
        app.text_area[0].set_value("invalid json").run()
        app.button[0].click().run()
        self.assertTrue(app.error)
        self.assertFalse(app.exception)
        self.assertEqual(len(app.metric), 0)
