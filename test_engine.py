import json
import unittest
from pathlib import Path
from engine import check_response, run_suite


class EngineTests(unittest.TestCase):
    def test_exact_and_failure(self):
        self.assertTrue(check_response("4", "4", "exact"))
        self.assertFalse(check_response("4 ", "4", "exact"))

    def test_substring_default(self):
        self.assertTrue(check_response("Привет, мир", "привет"))
        self.assertFalse(check_response("другое", "привет"))

    def test_json(self):
        self.assertTrue(check_response('{"b":2,"a":1}', '{"a":1,"b":2}', "json"))
        self.assertFalse(check_response("not json", "{}", "json"))
        self.assertFalse(check_response('{"a":2}', '{"a":1}', "json"))

    def test_demo_report(self):
        cases = json.loads(Path(__file__).with_name("scenarios.json").read_text(encoding="utf-8"))
        report = run_suite(cases)
        self.assertEqual((report["total"], report["passed"], report["cost_usd"]), (3, 3, 0))
        json.dumps(report)

    def test_json_booleans_are_not_numbers(self):
        self.assertFalse(check_response('{"ok":1}', '{"ok":true}', "json"))
        self.assertFalse(check_response('{"items":[false]}', '{"items":[0]}', "json"))
        self.assertTrue(check_response('{"count":1.0}', '{"count":1}', "json"))

    def test_failure_and_agent_exception(self):
        cases = [{"id": "bad", "prompt": "unknown", "expected": "correct", "check": "exact"}]
        self.assertEqual(run_suite(cases)["passed"], 0)
        def broken(prompt):
            raise RuntimeError("offline")
        report = run_suite(cases, broken)
        self.assertEqual(report["passed"], 0)
        self.assertIn("offline", report["results"][0]["error"])

    def test_invalid_cases(self):
        for cases in ({}, [], [None], [{"id": "x"}],
                      [{"id": "x", "prompt": "p", "expected": "e", "check": "bad"}],
                      [{"id": "x", "prompt": "p", "expected": "{", "check": "json"}]):
            with self.subTest(cases=cases), self.assertRaises(ValueError):
                run_suite(cases)

    def test_duplicate_ids(self):
        case = {"id": "x", "prompt": "p", "expected": "e"}
        with self.assertRaises(ValueError):
            run_suite([case, case])


if __name__ == "__main__":
    unittest.main()
