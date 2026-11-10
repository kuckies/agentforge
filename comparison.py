"""Sequential A/B runs on one frozen scenario set, persisted atomically."""
from contextlib import ExitStack
import copy
from datetime import datetime, timezone
import hashlib
import json
import statistics
from agents import LocalHTTPAgent
from engine import run_suite, validate_cases
from history import compare_runs, save_comparison
from local_models import ensure_model


def execute_comparison(cases, agent_a, agent_b, label_a, label_b, progress=None, path=None):
    frozen = copy.deepcopy(cases)
    validate_cases(frozen)
    if any("steps" in case for case in frozen):
        raise ValueError("Сравнение локальных моделей принимает отдельные запросы, а не диалоги бота")
    reports = {}
    for index, (variant, agent) in enumerate((("a",agent_a),("b",agent_b))):
        callback = (lambda done,total,offset=index: progress(offset*len(frozen)+done,2*len(frozen))) if progress else None
        reports[variant] = run_suite(copy.deepcopy(frozen),agent,progress=callback)
    changes = compare_runs(reports["a"],reports["b"])
    summary = {"improved":sum(row["изменение"]=="Исправлен" for row in changes),
               "regressed":sum(row["изменение"]=="Новый провал" for row in changes)}
    for variant,report in reports.items():
        times = [r["latency_ms"] for r in report["results"] if not r["error"]]
        summary[variant] = {"passed":report["passed"],"total":report["total"],
                            "technical_errors":sum(bool(r["error"]) for r in report["results"]),
                            "median_latency_ms":round(statistics.median(times),3) if times else None}
    bundle = {"schema_version":1,"kind":"comparison","created_at":datetime.now(timezone.utc).isoformat(),
              "labels":{"a":label_a,"b":label_b},"scenarios":frozen,
              "scenarios_sha256":hashlib.sha256(json.dumps(frozen,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
              "summary":summary,"changes":changes,**reports}
    return save_comparison(bundle,path)


def run_local_comparison(cases, profile_a, instruction_a, profile_b, instruction_b,
                         label_a, label_b, progress=None, status=None):
    validate_cases(cases)
    if any("steps" in case for case in cases):
        raise ValueError("Для сравнения выберите набор одиночных запросов")
    with ExitStack() as stack:
        configs = {}
        for profile in dict.fromkeys((profile_a,profile_b)):
            if status:
                status(f"Подготавливаю {profile}…")
            configs[profile] = stack.enter_context(ensure_model(profile))
        def agent(profile,instruction):
            config = configs[profile]
            return LocalHTTPAgent(f'http://127.0.0.1:{config["port"]}/v1/chat/completions',config["alias"],system=instruction)
        if status:
            status("Запускаю A, затем B на одинаковых задачах…")
        return execute_comparison(cases,agent(profile_a,instruction_a),agent(profile_b,instruction_b),
                                  label_a,label_b,progress=progress)
