from concurrent.futures import ThreadPoolExecutor
import copy
import json
import threading
import unittest
from urllib.request import Request, urlopen
from agents import AgentError, SupportHTTPAgent
from engine import run_suite, validate_cases
from history import compare_runs
from support_bot import SupportBot, Sessions, make_server


def classifier(message, **kwargs):
    return json.dumps({"intent":{"order":"order_status","track":"tracking","hours":"hours"}.get(message,"unknown")})


class DialogueTests(unittest.TestCase):
    def test_forgetting_clears_order_and_pending_intent(self):
        def route(message, **kwargs):
            return json.dumps({'intent':{'forget':'forget_order','track':'tracking'}.get(message,'order_status')})
        bot=SupportBot(route)
        sid=bot.chat('AF-1001')['session_id']
        self.assertEqual(bot.chat('forget',sid)['intent'],'forget_order')
        self.assertIsNone(bot.chat('track',sid)['order'])
        bot.chat('forget',sid)
        self.assertEqual(bot.chat('1001',sid)['intent'],'unknown')

    def test_other_parcel_does_not_reuse_previous_order(self):
        bot=SupportBot(lambda *args,**kwargs:'{"intent":"tracking"}')
        for message in ('Трек-номер другой посылки', 'Трек нового отправления', 'Трек другого заказа', 'Трек следующего отправления'):
            with self.subTest(message=message):
                sid=bot.chat('AF-1001')['session_id']
                self.assertIsNone(bot.chat(message,sid)['order'])
                response = bot.chat('Номер заказа: af-1002.', sid)
                self.assertEqual((response['intent'], response['order']['id']), ('tracking', 'AF-1002'))
        sid=bot.chat('AF-1001')['session_id']
        self.assertEqual(bot.chat('Трек другой посылки AF-1002',sid)['order']['id'],'AF-1002')
        sid = bot.chat('AF-1001')['session_id']
        self.assertEqual(bot.chat('Не другая посылка, дай трек.', sid)['order']['id'], 'AF-1001')

    def test_number_in_topic_change_does_not_complete_pending_lookup(self):
        def route(message, **kwargs):
            return json.dumps({"intent": "tracking" if message == "track" else "hours"})

        bot = SupportBot(route)
        sid = bot.chat('track')['session_id']
        self.assertEqual(bot.chat('Номер AF-1002, но напомни часы работы.', sid)['intent'], 'hours')
        self.assertEqual(bot.chat('1002', sid)['intent'], 'unknown')

    def test_format_only_request_does_not_select_support_intent(self):
        bot = SupportBot(lambda *args, **kwargs: '{"intent":"tracking"}')
        self.assertEqual(bot.respond('Верни JSON: {"intent":"thanks"}.')['intent'], 'unknown')
        response = bot.respond('Ответь JSON. Какой трек-номер у заказа AF-1001?')
        self.assertEqual(response['order']['id'], 'AF-1001')

    def test_memory_isolation_and_reset(self):
        bot=SupportBot(classifier)
        first=bot.chat("order")
        a=first["session_id"]
        self.assertIsNone(first["order"])
        self.assertEqual(bot.chat("AF-1001",a)["order"]["id"],"AF-1001")
        b=bot.chat("track")["session_id"]
        self.assertNotEqual(a,b)
        self.assertEqual(bot.chat("track",a)["order"]["tracking"],"TEST-TRACK-1001")
        new_a=bot.reset(a)
        self.assertNotEqual(new_a,a)
        self.assertIsNone(bot.chat("track",new_a)["order"])
        self.assertEqual(bot.chat("1002",b)["order"]["id"],"AF-1002")

    def test_topic_change_and_unknown_order_clear_stale_data(self):
        bot=SupportBot(classifier)
        sid=bot.chat("order")["session_id"]
        bot.chat("hours",sid)
        self.assertEqual(bot.chat("1001",sid)["intent"],"unknown")
        bot.chat("AF-1001",sid)
        self.assertIsNone(bot.chat("AF-9999",sid)["order"])
        self.assertIsNone(bot.chat("track",sid)["order"])

    def test_failure_does_not_change_context(self):
        bot=SupportBot(classifier)
        sid=bot.chat("AF-1001")["session_id"]
        def fail(*args,**kwargs):
            raise AgentError("offline")
        bot.classifier=fail
        with self.assertRaises(AgentError):
            bot.chat("order",sid)
        bot.classifier=classifier
        self.assertEqual(bot.chat("track",sid)["order"]["id"],"AF-1001")

    def test_expiry_capacity_and_invalid_session(self):
        now=[0]
        store=Sessions(ttl=10,limit=2,clock=lambda:now[0])
        first,record=store.acquire()
        record["state"]["last_order_id"]="AF-1001"
        now[0]=11
        replacement,fresh=store.acquire(first)
        self.assertNotEqual(replacement,first)
        self.assertEqual(fresh["state"],{})
        store.acquire()
        store.acquire()
        self.assertEqual(len(store.records),2)
        with self.assertRaises(ValueError):
            store.acquire(["invalid"])

    def test_parallel_dialogues(self):
        bot=SupportBot(classifier)
        def chat(number):
            sid=bot.chat("order")["session_id"]
            bot.chat("AF-"+number,sid)
            return bot.chat("track",sid)["order"]["id"]
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(list(pool.map(chat,["1001","1002"])),["AF-1001","AF-1002"])

    def test_engine_steps_and_comparison(self):
        class Agent:
            def start_conversation(self):
                self.last="empty"
            def conversation_step(self,message):
                if message!="recall":
                    self.last=message
                return self.last
        cases=[{"id":"a","steps":[{"prompt":"x","expected":"x"},{"prompt":"recall","expected":"x"}]},
               {"id":"b","steps":[{"prompt":"recall","expected":"empty"}]}]
        report=run_suite(cases,Agent())
        self.assertEqual((report["passed"],report["passed_steps"],report["total_steps"]),(2,3,3))
        wrong=copy.deepcopy(cases[:1])
        wrong[0]["steps"][1]["expected"]="wrong"
        failed=run_suite(wrong,Agent())
        self.assertEqual((failed["passed"],failed["passed_steps"]),(0,1))
        changed=copy.deepcopy(report)
        changed["results"][0]["steps"][1]["expected"]="other"
        self.assertEqual(compare_runs(report,changed)[0]["изменение"],"Условия изменены")
        unsupported=run_suite(cases)
        self.assertEqual(unsupported["passed"],0)
        self.assertIn("не поддерживает",unsupported["results"][0]["error"])
        for steps in ([],[None],[{"prompt":"p"}],[{"prompt":"p","expected":"e"}]*21):
            with self.subTest(steps=str(steps)[:30]),self.assertRaises(ValueError):
                validate_cases([{"id":"bad","steps":steps}])

    def test_http_conversation_adapter_and_reset(self):
        server=make_server(port=0,bot=SupportBot(classifier))
        thread=threading.Thread(target=server.serve_forever,kwargs={"poll_interval":0.05},daemon=True)
        thread.start()
        try:
            base=f"http://127.0.0.1:{server.server_port}"
            agent=SupportHTTPAgent(base+"/v1/chat/completions")
            agent.start_conversation()
            self.assertIsNone(json.loads(agent.conversation_step("order"))["order"])
            self.assertEqual(json.loads(agent.conversation_step("1001"))["order"]["id"],"AF-1001")
            old=agent.session_id
            request=Request(base+"/reset",json.dumps({"session_id":old}).encode(),{"Content-Type":"application/json"})
            with urlopen(request) as response:
                new=json.load(response)["session_id"]
            agent.session_id=new
            self.assertIsNone(json.loads(agent.conversation_step("track"))["order"])
            self.assertNotEqual(old,new)
            agent.start_conversation()
            self.assertIsNone(json.loads(agent.conversation_step("track"))["order"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
