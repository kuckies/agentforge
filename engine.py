"""Agent evaluation engine with an offline demo by default."""
import json
from datetime import datetime, timezone
from time import perf_counter


def json_equal(left, right):
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(json_equal(left[key], right[key]) for key in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(json_equal(a, b) for a, b in zip(left, right))
    return left == right


def check_response(actual, expected, kind="substring"):
    if kind == "exact":
        return actual == expected
    if kind == "substring":
        return str(expected).casefold() in actual.casefold()
    if kind == "json":
        try:
            return json_equal(json.loads(actual), json.loads(expected))
        except (TypeError, ValueError):
            return False
    raise ValueError(f"Unknown check: {kind}")


def validate_cases(cases):
    if not isinstance(cases, list) or not cases:
        raise ValueError("Нужен непустой JSON-массив сценариев")
    if len(cases) > 100:
        raise ValueError("Максимум 100 сценариев за запуск")
    identifiers = set()
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("Каждый сценарий должен быть объектом")
        for key in ("id",):
            if not isinstance(case.get(key), str) or not case[key].strip():
                raise ValueError(f"Поле {key} должно быть непустой строкой")
        if case["id"] in identifiers:
            raise ValueError("id сценариев должны быть уникальны")
        identifiers.add(case["id"])
        targets = case.get("steps", [case])
        if not isinstance(targets, list) or not 1 <= len(targets) <= 20:
            raise ValueError("В диалоге нужно от 1 до 20 шагов")
        for target in targets:
            validate_answer_case(target)
    return cases


def validate_answer_case(case):
    if not isinstance(case, dict):
        raise ValueError("Шаг должен быть объектом")
    for key in ("prompt", "expected"):
        if not isinstance(case.get(key), str) or not case[key].strip():
            raise ValueError(f"Поле {key} должно быть непустой строкой")
    if case.get("check", "substring") not in ("substring", "exact", "json"):
        raise ValueError("Проверка: substring, exact или json")
    if case.get("output_format", "text") not in ("text", "json"):
        raise ValueError("output_format: text или json")
    if case.get("check") == "json":
        try:
            json.loads(case["expected"])
        except ValueError as exc:
            raise ValueError("expected для json должен содержать корректный JSON") from exc


def demo_agent(prompt):
    """Predictable fixtures, deliberately not a language model."""
    return {
        "Скажи привет": "Привет! Я демонстрационный агент.",
        "Сколько будет 2+2?": "4",
        "Верни JSON со статусом ok": '{"status": "ok"}',
    }.get(prompt, "Демо-агент не знает ответа на этот запрос.")


def evaluate_answer(case, agent):
    started = perf_counter()
    actual, error = "", None
    try:
        actual = (agent(case["prompt"], output_format="json")
                  if case.get("output_format") == "json" else agent(case["prompt"]))
        if not isinstance(actual, str):
            raise TypeError("Agent must return a string")
        passed = check_response(actual, case["expected"], case.get("check", "substring"))
    except Exception as exc:
        passed, error = False, f"{type(exc).__name__}: {exc}"
    return {**case, "actual": actual, "passed": passed,
                    "latency_ms": round((perf_counter() - started) * 1000, 3),
                    "error": error}


def run_suite(cases, agent=demo_agent, progress=None):
    validate_cases(cases)
    results = []
    for case in cases:
        if "steps" not in case:
            result = evaluate_answer(case, agent)
        else:
            started = perf_counter()
            step_results, error = [], None
            try:
                if not hasattr(agent, "start_conversation") or not hasattr(agent, "conversation_step"):
                    raise ValueError("Этот агент не поддерживает диалоги")
                agent.start_conversation()
                step_results = [evaluate_answer(step, agent.conversation_step) for step in case["steps"]]
                if any(step["error"] for step in step_results):
                    error = "Техническая ошибка на одном или нескольких шагах"
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
            result = {**case,"actual":json.dumps([step["actual"] for step in step_results], ensure_ascii=False),
                      "passed":bool(step_results) and all(step["passed"] for step in step_results),
                      "error":error, "step_results":step_results,
                      "latency_ms":round((perf_counter()-started)*1000,3)}
        results.append(result)
        if progress:
            progress(len(results), len(cases))
    metadata = (agent.metadata() if hasattr(agent, "metadata") else
                {"provider": "demo" if agent is demo_agent else "custom"})
    return {"schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
            "provider": metadata["provider"], "agent": metadata,
            "cost_usd": 0 if metadata["provider"] in ("demo", "local_http") else None,
            "total": len(results), "passed": sum(r["passed"] for r in results),
            "total_steps":sum(len(case.get("steps", [case])) for case in cases),
            "passed_steps":sum(sum(step["passed"] for step in r["step_results"]) if "step_results" in r else r["passed"] for r in results),
            "results": results}
