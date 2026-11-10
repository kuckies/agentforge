"""Local HTTP adapters. No API keys, redirects, proxies or remote endpoints."""
import ipaddress
import json
import socket
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler


class AgentError(RuntimeError):
    pass


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class LocalHTTPAgent:
    def __init__(self, endpoint="http://127.0.0.1:8081/v1/chat/completions",
                 model="qwen-local", protocol="openai", timeout=60,
                 system="Следуй инструкции пользователя. Отвечай кратко, без пояснений."):
        parsed = urlsplit(endpoint)
        try:
            local = ipaddress.ip_address(parsed.hostname or "").is_loopback
            port = parsed.port
        except ValueError:
            local, port = False, None
        if (parsed.scheme != "http" or not local or not port or parsed.username
                or parsed.password or parsed.query or parsed.fragment):
            raise ValueError("Укажите локальный HTTP-адрес с IP 127.0.0.1 или ::1 и портом")
        if protocol not in ("openai", "ollama"):
            raise ValueError("Неизвестный протокол агента")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("Укажите название модели")
        if not 0 < timeout <= 300:
            raise ValueError("Тайм-аут должен быть от 0 до 300 секунд")
        self.endpoint, self.model, self.protocol = endpoint, model, protocol
        self.timeout, self.system = timeout, system
        self.opener = build_opener(ProxyHandler({}), NoRedirects())

    def metadata(self):
        metadata = {"provider": "local_http", "protocol": self.protocol,
                "endpoint": self.endpoint, "model": self.model,
                "system_prompt": self.system, "temperature": 0, "seed": 42,
                "max_output_tokens": 128, "timeout_seconds": self.timeout}
        if isinstance(getattr(self, "server_metadata", None), dict):
            metadata["server"] = self.server_metadata
        return metadata

    def __call__(self, prompt, *, output_format="text"):
        if output_format not in ("text", "json"):
            raise ValueError("Формат ответа должен быть text или json")
        if self.protocol == "openai":
            payload = {"model": self.model, "stream": False,
                       "messages": [{"role": "system", "content": self.system},
                                    {"role": "user", "content": prompt}],
                       "temperature": 0, "seed": 42, "max_tokens": 128}
            if output_format == "json":
                payload["response_format"] = {"type": "json_object"}
        else:
            payload = {"model": self.model, "prompt": prompt, "system": self.system,
                       "stream": False, "options": {"temperature": 0, "seed": 42,
                                                     "num_predict": 128, "num_ctx": 2048}}
            if output_format == "json":
                payload["format"] = "json"
        request = Request(self.endpoint, json.dumps(payload).encode("utf-8"),
                          headers={"Content-Type": "application/json"}, method="POST")
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                data = response.read(1024 * 1024 + 1)
            if len(data) > 1024 * 1024:
                raise AgentError("Ответ сервера превышает 1 МБ")
            decoded = json.loads(data)
            self.server_metadata = decoded.get("agent") if isinstance(decoded, dict) else None
            actual = (decoded["choices"][0]["message"]["content"]
                      if self.protocol == "openai" else decoded["response"])
            if not isinstance(actual, str):
                raise TypeError("Expected string response")
            return actual
        except HTTPError as exc:
            exc.close()
            if exc.code == 404:
                raise AgentError("HTTP 404: проверьте адрес API и наличие модели") from exc
            raise AgentError(f"Сервер вернул HTTP {exc.code}") from exc
        except (TimeoutError, socket.timeout) as exc:
            raise AgentError(f"Сервер не ответил за {self.timeout} с") from exc
        except URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise AgentError(f"Сервер не ответил за {self.timeout} с") from exc
            raise AgentError("Нет соединения с локальным агентом. Запустите сервер модели.") from exc
        except (ValueError, KeyError, IndexError, TypeError, UnicodeError) as exc:
            raise AgentError("Неверный ответ API: ожидался JSON с текстом ответа") from exc


class SupportHTTPAgent(LocalHTTPAgent):
    def __init__(self, endpoint="http://127.0.0.1:8085/v1/chat/completions", timeout=60):
        super().__init__(endpoint, model="support-bot", timeout=timeout, system="")

    def metadata(self):
        result = super().metadata()
        result.update(agent_kind="support_bot", system_prompt="Политика бота задаётся на его сервере")
        parsed = urlsplit(self.endpoint)
        result["conversation_endpoint"] = f"{parsed.scheme}://{parsed.netloc}/chat"
        return result

    def start_conversation(self):
        self.session_id = None

    def conversation_step(self, prompt, *, output_format="text"):
        parsed = urlsplit(self.endpoint)
        url = f"{parsed.scheme}://{parsed.netloc}/chat"
        request = Request(url, json.dumps({"message":prompt,"session_id":getattr(self,"session_id",None)}).encode(),
                          {"Content-Type":"application/json"}, method="POST")
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise AgentError("Ответ бота превышает 1 МБ")
            result = json.loads(raw)
            if isinstance(result, dict) and "session_id" not in result:
                raise AgentError("Запущена старая версия бота. Перезапустите Start-TestBot.cmd для диалогов.")
            session_id = result["session_id"]
            if not isinstance(session_id, str) or not isinstance(result["reply"], str):
                raise ValueError("Неверный ответ бота")
            self.session_id = session_id
            self.server_metadata = result.get("agent")
            return json.dumps({key:result[key] for key in ("intent","reply","order")}, ensure_ascii=False)
        except HTTPError as exc:
            exc.close()
            raise AgentError(f"Бот вернул HTTP {exc.code}") from exc
        except (TimeoutError, socket.timeout) as exc:
            raise AgentError("Истекло время ожидания ответа бота") from exc
        except URLError as exc:
            raise AgentError("Нет соединения с ботом. Запустите Start-TestBot.cmd.") from exc
        except (ValueError, KeyError, TypeError, UnicodeError) as exc:
            raise AgentError("Неверный формат ответа диалога") from exc
