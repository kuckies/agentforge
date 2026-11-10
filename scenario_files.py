"""Import JSON as data only; never evaluate uploaded content."""
import hashlib
import json
from engine import validate_cases

MAX_FILE_BYTES = 1024 * 1024


def parse_scenarios(data):
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("Файл слишком большой: максимум 1 МБ")
    try:
        payload = json.loads(data.decode("utf-8-sig"))
    except UnicodeError as exc:
        raise ValueError("Сохраните файл в кодировке UTF-8") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Ошибка JSON: строка {exc.lineno}, столбец {exc.colno}") from exc
    except RecursionError as exc:
        raise ValueError("Слишком глубокая вложенность JSON") from exc
    if isinstance(payload, dict):
        if "results" in payload or payload.get("kind") == "comparison":
            raise ValueError("Это отчёт о запуске. Для загрузки нужен файл сценариев, скачанный кнопкой «Скачать сценарии»")
        payload = payload.get("scenarios")
    validate_cases(payload)
    return payload


def apply_upload(data, state, target="scenarios", marker="scenario_import_fingerprint"):
    cases = parse_scenarios(data)
    fingerprint = hashlib.sha256(data).hexdigest()
    if state.get(marker) != fingerprint:
        state[target] = json.dumps(cases,ensure_ascii=False,indent=2)
        state[marker] = fingerprint
    return cases
