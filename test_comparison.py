import copy
import json
import os
import io
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from unittest.mock import MagicMock
from urllib.error import URLError
from streamlit.testing.v1 import AppTest
from comparison import execute_comparison
from history import list_comparisons, list_runs, load_comparison, load_run, save_comparison
from local_models import ensure_model


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.db = Path(temp.name)/"history.sqlite3"
        env = patch.dict(os.environ,{"AGENTFORGE_DB_PATH":str(self.db)})
        env.start()
        self.addCleanup(env.stop)

    def test_pair_progress_persistence_and_unchanged_cases(self):
        cases = [{"id":"x","prompt":"p","expected":"right","check":"exact"}]
        frozen = copy.deepcopy(cases)
        progress = []
        result = execute_comparison(cases,lambda prompt:"wrong",lambda prompt:"right","before","after",
                                    progress=lambda done,total:progress.append((done,total)))
        self.assertEqual(cases,frozen)
        self.assertEqual(progress,[(1,2),(2,2)])
        self.assertEqual(result["summary"]["improved"],1)
        self.assertEqual(len(list_runs()),2)
        self.assertEqual(len(list_comparisons()),1)
        self.assertEqual(load_comparison(result["comparison_id"]),result)
        self.assertEqual(load_run(result["run_ids"]["a"]),result["a"])
        self.assertEqual(load_run(result["run_ids"]["b"]),result["b"])

    def test_technical_failure_is_not_quality_improvement(self):
        def offline(prompt):
            raise RuntimeError("offline")
        result = execute_comparison([{"id":"x","prompt":"p","expected":"right"}],offline,lambda prompt:"right","A","B")
        self.assertEqual(result["summary"]["a"]["technical_errors"],1)
        self.assertEqual(result["summary"]["improved"],0)
        self.assertEqual(result["changes"][0]["изменение"],"Ошибка устранена")

    def test_atomic_pair_failure(self):
        bundle = {"created_at":"now","labels":{"a":"A","b":"B"},
                  "a":{"created_at":"now","provider":"test","total":1,"passed":1},
                  "b":{"invalid":True}}
        with self.assertRaises(KeyError):
            save_comparison(bundle)
        self.assertEqual(list_runs(),[])
        self.assertEqual(list_comparisons(),[])

    def test_one_button_and_reopen_comparison(self):
        def fake(cases,profile_a,instruction_a,profile_b,instruction_b,label_a,label_b,**kwargs):
            self.assertEqual(profile_a,profile_b)
            self.assertNotEqual(instruction_a,instruction_b)
            return execute_comparison(cases,lambda prompt:"wrong",lambda prompt:"right",label_a,label_b)
        path = str(Path(__file__).with_name("app.py"))
        with patch("comparison_ui.run_local_comparison",side_effect=fake) as called:
            app = AppTest.from_file(path).run(timeout=30)
            app.button(key="compare_run").click().run(timeout=30)
            self.assertFalse(app.exception)
            self.assertEqual(called.call_count,1)
            self.assertEqual(len(list_runs()),2)
            saved = app.session_state["comparison_result"]
            app.run()
            self.assertEqual(len(list_runs()),2)
            reopened = AppTest.from_file(path).run(timeout=30)
            self.assertFalse(reopened.exception)
            self.assertEqual(reopened.selectbox(key="comparison_history_id").value,saved["comparison_id"])

    def test_existing_wrong_model_is_not_replaced(self):
        opener=MagicMock()
        opener.open.side_effect=[io.BytesIO(b'{}'),io.BytesIO(b'{}'),io.BytesIO(b'{"data":[{"id":"different"}]}')]
        with patch("local_models.build_opener",return_value=opener),patch("local_models.subprocess.Popen") as launch:
            with self.assertRaisesRegex(RuntimeError,"другая модель"):
                with ensure_model("Qwen 7B"):
                    self.fail("Wrong model must not be accepted")
            launch.assert_not_called()

    def test_owned_process_is_stopped_even_on_failure(self):
        opener=MagicMock()
        opener.open.side_effect=[URLError(ConnectionRefusedError()),io.BytesIO(b'{}'),io.BytesIO(b'{"data":[{"id":"qwen-1.5b"}]}')]
        process=MagicMock()
        process.poll.return_value=None
        with patch("local_models.build_opener",return_value=opener),patch("local_models.Path.is_file",return_value=True),\
             patch("local_models.Path.open",return_value=io.StringIO()),patch("local_models.subprocess.Popen",return_value=process):
            with self.assertRaisesRegex(RuntimeError,"test failure"):
                with ensure_model("Qwen 1.5B"):
                    raise RuntimeError("test failure")
        process.terminate.assert_called_once()
        process.wait.assert_called_once()
