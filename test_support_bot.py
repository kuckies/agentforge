import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from streamlit.testing.v1 import AppTest
from agents import AgentError, SupportHTTPAgent
from support_bot import SupportBot, make_server, REPLIES


class SupportBotTests(unittest.TestCase):
    def test_hard_dialogues_are_selectable_without_model(self):
        app=AppTest.from_file(str(Path(__file__).with_name('app.py'))).run(timeout=30)
        app.selectbox[0].select('Бот поддержки (учебный)').run()
        for label,count,steps in [('Сложные диалоги — 12',12,32),('Контрольные диалоги — 20',20,49)]:
            with self.subTest(suite=label):
                app.selectbox(key='support_suite').select(label).run()
                self.assertFalse(app.exception)
                cases=json.loads(app.session_state['scenarios'])
                self.assertEqual(len(cases),count)
                self.assertEqual(sum(len(c['steps']) for c in cases),steps)
                self.assertEqual(len({c['id'] for c in cases}),count)

    def test_orders_are_read_from_database(self):
        bot = SupportBot(lambda message, **kwargs: '{"intent":"order_status"}')
        self.assertEqual(bot.respond("заказ af-1002")["order"]["status"], "processing")
        self.assertIsNone(bot.respond("заказ AF-9999")["order"])
        self.assertIn("не найден", bot.respond("заказ AF-9999")["reply"])
        self.assertIn("Укажите номер", bot.respond("мой заказ")["reply"])
        self.assertIn("один номер", bot.respond("AF-1001 и AF-1002")["reply"])

    def test_faq_and_invalid_routing(self):
        bot = SupportBot(lambda message, **kwargs: '{"intent":"delivery"}')
        self.assertEqual(bot.respond("доставка")["reply"], REPLIES["delivery"])
        for payload in ("not json", "{}", '{"intent":"invented"}', '{"intent":[]}'):
            with self.subTest(payload=payload), self.assertRaises(AgentError):
                SupportBot(lambda message, **kwargs: payload).respond("hello")

    def test_invalid_input_does_not_call_model(self):
        def forbidden(*args, **kwargs):
            self.fail("Model should not be called")
        for message in (None, "", "   ", "x" * 4001):
            with self.subTest(message=str(message)[:20]), self.assertRaises(ValueError):
                SupportBot(forbidden).respond(message)

    def test_api_chat_and_agentforge_integration(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        with patch.dict(os.environ, {"AGENTFORGE_DB_PATH":str(Path(temp.name) / "test.sqlite3")}):
            bot = SupportBot(lambda message, **kwargs: '{"intent":"thanks"}')
            server = make_server(port=0, bot=bot)
            thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval":0.05}, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_port}"
                with urlopen(base) as response:
                    self.assertIn("ForgeShop", response.read().decode())
                request = Request(base + "/chat", json.dumps({"message":"Спасибо"}).encode(), {"Content-Type":"application/json"})
                with urlopen(request) as response:
                    self.assertEqual(json.load(response)["intent"], "thanks")
                bad = Request(base + "/chat", b'{"message":""}', {"Content-Type":"application/json"})
                with self.assertRaises(HTTPError) as caught:
                    urlopen(bad)
                self.assertEqual(caught.exception.code, 400)
                caught.exception.close()
                agent = SupportHTTPAgent(base + "/v1/chat/completions")
                self.assertEqual(json.loads(agent("Спасибо"))["reply"], REPLIES["thanks"])
                self.assertEqual(agent.metadata()["server"]["policy_version"], "support-v3")
                app = AppTest.from_file(str(Path(__file__).with_name("app.py"))).run(timeout=30)
                app.selectbox[0].select("Бот поддержки (учебный)").run()
                app.text_input(key="support_endpoint").set_value(base + "/v1/chat/completions")
                app.text_area(key="scenarios").set_value(json.dumps([{
                    "id":"thanks", "prompt":"Спасибо", "expected":json.dumps(bot.respond("Спасибо")), "check":"json"}]))
                app.button[0].click().run(timeout=30)
                self.assertFalse(app.exception)
                self.assertEqual(app.metric[0].value, "1 / 1")
                self.assertEqual(app.session_state["report"]["agent"]["agent_kind"], "support_bot")
                def unavailable(message, **kwargs):
                    raise AgentError("Модель недоступна")
                bot.classifier = unavailable
                with self.assertRaises(HTTPError) as failed:
                    urlopen(request)
                self.assertEqual(failed.exception.code, 502)
                failed.exception.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
