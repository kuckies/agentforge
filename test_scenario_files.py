from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
from comparison import execute_comparison
from scenario_files import apply_upload, parse_scenarios, MAX_FILE_BYTES


class Uploaded(io.BytesIO):
    name="my-scenarios.json"


class ScenarioFileTests(unittest.TestCase):
    def setUp(self):
        temp=TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        env=patch.dict(os.environ,{"AGENTFORGE_DB_PATH":str(Path(temp.name)/"history.sqlite3")})
        env.start()
        self.addCleanup(env.stop)
        self.cases=[{"id":"custom","prompt":"Сколько будет 2+2?","expected":"4","check":"exact"}]
        self.data=json.dumps(self.cases,ensure_ascii=False).encode()

    def test_utf8_bom_and_wrapped_json(self):
        self.assertEqual(parse_scenarios(b'\xef\xbb\xbf'+self.data),self.cases)
        self.assertEqual(parse_scenarios(json.dumps({"scenarios":self.cases}).encode()),self.cases)

    def test_reject_bad_encoding_size_and_reports(self):
        for data in (b'\xff',b'not json',b' '* (MAX_FILE_BYTES+1),b'{"results":[]}',b'{"kind":"comparison"}',b'[]'):
            with self.subTest(data=data[:40]),self.assertRaises(ValueError):
                parse_scenarios(data)
        with self.assertRaises(ValueError):
            parse_scenarios(json.dumps(self.cases*2).encode())

    def test_upload_preserves_manual_edits_and_rejects_atomically(self):
        state={}
        apply_upload(self.data,state)
        state["scenarios"]="manually edited"
        apply_upload(self.data,state)
        self.assertEqual(state["scenarios"],"manually edited")
        before=state.copy()
        with self.assertRaises(ValueError):
            apply_upload(b'bad',state)
        self.assertEqual(state,before)

    def test_tabs_upload_and_demo_run(self):
        def uploaded(*args,**kwargs):
            return Uploaded(self.data) if kwargs.get("key","").startswith("scenario_upload:") else None
        with patch("streamlit.file_uploader",side_effect=uploaded):
            app=AppTest.from_file(str(Path(__file__).with_name("app.py"))).run(timeout=30)
            self.assertFalse(app.exception)
            self.assertEqual([tab.label for tab in app.tabs],["Проверка","Сравнение","История","Помощь"])
            app.button(key="run_tests").click().run(timeout=30)
            self.assertFalse(app.exception)
            self.assertEqual(app.metric[0].value,"1 / 1")
            changed=json.loads(app.text_area(key="scenarios").value)
            changed[0]["expected"]="5"
            app.text_area(key="scenarios").set_value(json.dumps(changed)).run()
            app.button(key="run_tests").click().run(timeout=30)
            self.assertEqual(app.metric[0].value,"0 / 1")

    def test_invalid_upload_blocks_run(self):
        def uploaded(*args,**kwargs):
            return Uploaded(b'broken') if kwargs.get("key","").startswith("scenario_upload:") else None
        with patch("streamlit.file_uploader",side_effect=uploaded):
            app=AppTest.from_file(str(Path(__file__).with_name("app.py"))).run(timeout=30)
            self.assertFalse(app.exception)
            self.assertTrue(app.error)
            self.assertTrue(app.button(key="run_tests").disabled)

    def test_file_is_shared_by_both_comparison_variants(self):
        def uploaded(*args,**kwargs):
            return Uploaded(self.data) if kwargs.get("key","").startswith("comparison_upload:") else None
        def compare(cases,pa,ia,pb,ib,la,lb,**kwargs):
            self.assertEqual(cases,self.cases)
            return execute_comparison(cases,lambda prompt:"3",lambda prompt:"4",la,lb)
        with patch("streamlit.file_uploader",side_effect=uploaded),patch("comparison_ui.run_local_comparison",side_effect=compare):
            app=AppTest.from_file(str(Path(__file__).with_name("app.py"))).run(timeout=30)
            app.button(key="compare_run").click().run(timeout=30)
            self.assertFalse(app.exception)
            result=app.session_state["comparison_result"]
            self.assertEqual(result["scenarios"],self.cases)
            self.assertEqual(result["summary"]["improved"],1)

    def test_own_local_agent_connection(self):
        requests=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):
                pass
            def do_POST(self):
                requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"choices":[{"message":{"content":"OK"}}]}')
        server=ThreadingHTTPServer(("127.0.0.1",0),Handler)
        thread=threading.Thread(target=server.serve_forever,kwargs={"poll_interval":0.05},daemon=True)
        thread.start()
        try:
            app=AppTest.from_file(str(Path(__file__).with_name("app.py"))).run(timeout=30)
            app.selectbox[0].select("Свой агент").run()
            app.text_input(key="endpoint-Свой агент-openai").set_value(f"http://127.0.0.1:{server.server_port}/v1/chat/completions")
            app.text_area(key="scenarios").set_value(json.dumps([{"id":"own","prompt":"hello","expected":"OK","check":"exact"}]))
            app.button(key="run_tests").click().run(timeout=30)
            self.assertFalse(app.exception)
            self.assertEqual(app.metric[0].value,"1 / 1")
            self.assertEqual(requests[0]["messages"][-1]["content"],"hello")
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
