import json
import os
from tempfile import TemporaryDirectory
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import time
import unittest
from pathlib import Path
from streamlit.testing.v1 import AppTest
from agents import AgentError, LocalHTTPAgent
from engine import run_suite


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        self.server.last_request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        status, body, delay = self.server.reply
        time.sleep(delay)
        self.send_response(status)
        if status == 302:
            self.send_header("Location", "https://example.com/")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass


class HTTPAgentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temp = TemporaryDirectory()
        cls.addClassCleanup(temp.cleanup)
        env = patch.dict(os.environ, {"AGENTFORGE_DB_PATH": str(Path(temp.name) / "test.sqlite3")})
        env.start()
        cls.addClassCleanup(env.stop)
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        cls.thread.start()
        cls.endpoint = f"http://127.0.0.1:{cls.server.server_port}/v1/chat/completions"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        self.server.reply = (200, b'{"choices":[{"message":{"content":"4"}}]}', 0)

    def test_openai_payload_and_report(self):
        agent = LocalHTTPAgent(self.endpoint)
        report = run_suite([{"id": "math", "prompt": "2+2?", "expected": "4", "check": "exact"}], agent)
        self.assertEqual(report["passed"], 1)
        self.assertEqual(report["provider"], "local_http")
        self.assertEqual(report["agent"]["model"], "qwen-local")
        self.assertEqual(self.server.last_request["messages"][-1]["content"], "2+2?")
        self.assertFalse(self.server.last_request["stream"])

    def test_ollama(self):
        self.server.reply = (200, b'{"response":"hello"}', 0)
        agent = LocalHTTPAgent(self.endpoint, model="test", protocol="ollama")
        self.assertEqual(agent("hi"), "hello")
        self.assertEqual(self.server.last_request["prompt"], "hi")

    def test_json_mode_and_content_validation(self):
        self.server.reply = (200, b'{"choices":[{"message":{"content":"{\\"status\\":\\"wrong\\"}"}}]}', 0)
        cases = [{"id": "json", "prompt": "Return status ok", "expected": '{"status":"ok"}',
                  "check": "json", "output_format": "json"}]
        report = run_suite(cases, LocalHTTPAgent(self.endpoint))
        self.assertEqual(self.server.last_request["response_format"], {"type": "json_object"})
        self.assertEqual(report["passed"], 0)
        self.assertEqual(report["results"][0]["actual"], '{"status":"wrong"}')
        self.assertEqual(report["results"][0]["output_format"], "json")
        self.assertIsNone(report["results"][0]["error"])

    def test_ollama_json_mode_and_plain_default(self):
        self.server.reply = (200, b'{"response":"{}"}', 0)
        agent = LocalHTTPAgent(self.endpoint, protocol="ollama")
        self.assertEqual(agent("json", output_format="json"), "{}")
        self.assertEqual(self.server.last_request["format"], "json")
        agent("plain")
        self.assertNotIn("format", self.server.last_request)

    def test_fenced_json_is_not_cleaned(self):
        body = {"choices": [{"message": {"content": '```json\n{"status":"ok"}\n```'}}]}
        self.server.reply = (200, json.dumps(body).encode(), 0)
        report = run_suite([{"id": "json", "prompt": "JSON", "expected": '{"status":"ok"}',
                            "check": "json", "output_format": "json"}], LocalHTTPAgent(self.endpoint))
        self.assertEqual(report["passed"], 0)
        self.assertTrue(report["results"][0]["actual"].startswith("```"))

    def test_http_errors_and_redirect(self):
        for status in (404, 500, 302):
            with self.subTest(status=status):
                self.server.reply = (status, b"error", 0)
                with self.assertRaisesRegex(AgentError, str(status)):
                    LocalHTTPAgent(self.endpoint)("hi")

    def test_invalid_responses(self):
        for body in (b"not json", b"{}", b'{"choices":[]}',
                     b'{"choices":[{"message":{"content":null}}]}'):
            self.server.reply = (200, body, 0)
            with self.subTest(body=body), self.assertRaisesRegex(AgentError, "JSON"):
                LocalHTTPAgent(self.endpoint)("hi")

    def test_timeout(self):
        self.server.reply = (200, b"{}", 0.2)
        with self.assertRaisesRegex(AgentError, "0.05"):
            LocalHTTPAgent(self.endpoint, timeout=0.05)("hi")

    def test_unavailable(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        port = server.server_port
        server.server_close()
        with self.assertRaisesRegex(AgentError, "Нет соединения"):
            LocalHTTPAgent(f"http://127.0.0.1:{port}/api")("hi")

    def test_nonlocal_rejected_before_request(self):
        for url in ("https://api.openai.com/v1/chat/completions", "http://example.com:80/api",
                    "http://127.0.0.1:80@evil.com:80/api", "http://localhost:8081/api"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                LocalHTTPAgent(url)

    def test_interface_with_http_agent(self):
        app = AppTest.from_file(str(Path(__file__).with_name("app.py"))).run(timeout=30)
        app.selectbox[0].select("Локальная модель").run()
        app.text_input[0].set_value(self.endpoint)
        app.text_area(key="scenarios").set_value(json.dumps([
            {"id": "math", "prompt": "2+2?", "expected": "4", "check": "exact"}]))
        app.button[0].click().run(timeout=30)
        self.assertFalse(app.exception)
        self.assertEqual(app.metric[0].value, "1 / 1")
        self.assertEqual(app.session_state["report"]["provider"], "local_http")
        app.selectbox[1].select("Qwen 1.5B").run()
        self.assertEqual(app.text_input[0].value, "http://127.0.0.1:8082/v1/chat/completions")
        self.assertEqual(app.text_input[1].value, "qwen-1.5b")
        app.button[1].click().run()
        examples = json.loads(app.text_area(key="scenarios").value)
        self.assertEqual(examples[-1]["output_format"], "json")
        app.radio(key="instruction_version").set_value("Уточнённая").run()
        from instructions import INSTRUCTIONS
        self.assertEqual(app.text_area(key="system_prompt").value, INSTRUCTIONS["Уточнённая"])
        app.text_input[0].set_value(self.endpoint)
        app.text_area(key="scenarios").set_value(json.dumps([
            {"id":"math","prompt":"2+2?","expected":"4","check":"exact"}]))
        app.button[0].click().run(timeout=30)
        self.assertFalse(app.exception)
        self.assertEqual(self.server.last_request["messages"][0]["content"], INSTRUCTIONS["Уточнённая"])
        self.assertEqual(app.session_state["report"]["agent"]["system_prompt"], INSTRUCTIONS["Уточнённая"])
        app.selectbox[1].select("Qwen 7B").run()
        self.assertEqual(app.text_input[0].value, "http://127.0.0.1:8084/v1/chat/completions")
        self.assertEqual(app.text_input[1].value, "qwen-7b")
        app.selectbox(key="suite").select("Контрольные задачи — 10").run()
        self.assertEqual(len(json.loads(app.text_area(key="scenarios").value)), 10)
