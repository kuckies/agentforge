"""Manage only local model processes started by this comparison."""
from contextlib import contextmanager
import json
from pathlib import Path
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.request import build_opener, ProxyHandler
import uuid

MODELS = {
    "Qwen 0.5B":{"port":8081,"alias":"qwen-local","file":"qwen2.5-0.5b-instruct-q4_k_m.gguf"},
    "Qwen 1.5B":{"port":8082,"alias":"qwen-1.5b","file":"qwen2.5-1.5b-instruct-q4_k_m.gguf"},
    "Qwen 7B":{"port":8084,"alias":"qwen-7b","file":"qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf"},
}


@contextmanager
def ensure_model(profile):
    config = MODELS[profile]
    base = f'http://127.0.0.1:{config["port"]}'
    opener = build_opener(ProxyHandler({}))
    process, log = None, None
    try:
        try:
            with opener.open(base + "/health", timeout=5):
                pass
        except HTTPError as exc:
            code = exc.code
            exc.close()
            if code != 503:
                raise RuntimeError(f"{profile}: сервер на порту {config['port']} вернул HTTP {code}") from exc
            # An existing model may still be loading. Wait without starting a second process.
        except URLError as exc:
            if not isinstance(exc.reason, ConnectionRefusedError):
                raise RuntimeError(f"{profile}: не удалось проверить локальный сервер") from exc
            folder = Path(__file__).resolve().parent
            runtime = folder.parent / "AgentForge-Runtime"
            model = runtime / "models" / config["file"]
            exe = runtime / "llama" / "llama-server.exe"
            required = [model, exe]
            if profile == "Qwen 7B":
                required.append(model.with_name(model.name.replace("00001", "00002")))
            if any(not path.is_file() for path in required):
                raise FileNotFoundError(f"{profile}: отсутствуют установленные файлы модели или движка")
            data = folder / "data"
            data.mkdir(exist_ok=True)
            log = (data / f"comparison-model-{uuid.uuid4().hex}.log").open("w", encoding="utf-8")
            process = subprocess.Popen([str(exe),"-m",str(model),"--host","127.0.0.1","--port",str(config["port"]),
                "--alias",config["alias"],"-c","2048","-ngl","99","--threads","6"],
                stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
        deadline = time.monotonic() + 180
        while True:
            if process is not None and process.poll() is not None:
                raise RuntimeError(f"{profile}: модель не запустилась; журнал находится в папке data")
            try:
                with opener.open(base + "/health", timeout=2):
                    break
            except HTTPError as exc:
                code = exc.code
                exc.close()
                if code != 503:
                    raise RuntimeError(f"{profile}: HTTP {code} при запуске") from exc
            except URLError:
                pass
            if time.monotonic() > deadline:
                raise RuntimeError(f"{profile}: время ожидания запуска истекло")
            time.sleep(0.5)
        with opener.open(base + "/v1/models", timeout=5) as response:
            identity = json.load(response)
        if config["alias"] not in [model.get("id") for model in identity.get("data",[])]:
            raise RuntimeError(f"На порту {config['port']} запущена другая модель. Её процесс не изменён.")
        yield config
    finally:
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        if log is not None:
            log.close()
