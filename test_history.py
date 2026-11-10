import copy
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
from engine import run_suite, validate_cases
from history import compare_runs, list_runs, load_run, save_run


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "nested" / "history.sqlite3"
        self.env = patch.dict(os.environ, {"AGENTFORGE_DB_PATH": str(self.db)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_persistence_and_distinct_runs(self):
        report = run_suite([{"id":"x", "prompt":"Сколько будет 2+2?", "expected":"4"}])
        first = save_run(report)
        second = save_run(report)
        self.assertNotEqual(first, second)
        self.assertEqual(load_run(first), report)
        self.assertEqual([r["id"] for r in list_runs()], [second, first])
        self.assertEqual(len(list_runs(limit=1)), 1)
        with self.assertRaises(KeyError):
            load_run("not-a-run")

    def test_comparison_distinguishes_rule_changes(self):
        before = {"results":[{"id":"x", "prompt":"p", "expected":"4", "passed":False, "actual":"3"}]}
        after = copy.deepcopy(before)
        after["results"][0].update(passed=True, actual="4")
        self.assertEqual(compare_runs(before, after)[0]["изменение"], "Исправлен")
        self.assertEqual(compare_runs(after, before)[0]["изменение"], "Новый провал")
        after["results"][0]["output_format"] = "json"
        self.assertEqual(compare_runs(before, after)[0]["изменение"], "Условия изменены")
        self.assertEqual(compare_runs(before, {"results":[]})[0]["изменение"], "Удалён")
        self.assertEqual(compare_runs({"results":[]}, before)[0]["изменение"], "Добавлен")

    def test_interface_survives_new_session_and_no_duplicate_on_rerun(self):
        path = str(Path(__file__).with_name("app.py"))
        app = AppTest.from_file(path).run(timeout=30)
        app.button[0].click().run(timeout=30)
        self.assertFalse(app.exception)
        self.assertEqual(len(list_runs()), 1)
        app.run()
        self.assertEqual(len(list_runs()), 1)
        reopened = AppTest.from_file(path).run(timeout=30)
        self.assertFalse(reopened.exception)
        self.assertEqual(len(reopened.selectbox(key="history_run").options), 1)
        reopened.button[0].click().run(timeout=30)
        self.assertFalse(reopened.exception)
        self.assertEqual(len(list_runs()), 2)
        reopened.checkbox(key="history_compare").check().run()
        self.assertEqual(len(reopened.selectbox(key="history_baseline").options), 2)

    def test_practical_suite(self):
        cases = json.loads(Path(__file__).with_name("scenarios-practical.json").read_text(encoding="utf-8"))
        validate_cases(cases)
        self.assertEqual(len(cases), 30)
        self.assertEqual(len({case["category"] for case in cases}), 6)
