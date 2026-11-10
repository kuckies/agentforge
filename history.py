"""Persistent local run history, with comparisons that respect scenario changes."""
from contextlib import contextmanager
import copy
import json
import os
from pathlib import Path
import sqlite3
import uuid


def default_database():
    return Path(os.environ.get("AGENTFORGE_DB_PATH", Path(__file__).with_name("data") / "agentforge.sqlite3"))


@contextmanager
def connection(path=None):
    path = Path(path) if path is not None else default_database()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    try:
        db.execute("""CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY, created_at TEXT NOT NULL, provider TEXT NOT NULL,
            model TEXT NOT NULL, total INTEGER NOT NULL, passed INTEGER NOT NULL,
            report_json TEXT NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS comparisons (
            id TEXT PRIMARY KEY, created_at TEXT NOT NULL, label_a TEXT NOT NULL,
            label_b TEXT NOT NULL, bundle_json TEXT NOT NULL)""")
        db.commit()
        yield db
    finally:
        db.close()


def save_run(report, path=None):
    run_id = uuid.uuid4().hex
    with connection(path) as db, db:
        insert_run(db, run_id, report)
    return run_id


def insert_run(db, run_id, report):
    payload = json.dumps(report, ensure_ascii=False, allow_nan=False)
    db.execute("INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?)",
               (run_id, report["created_at"], report["provider"],
                report.get("agent", {}).get("model", report["provider"]),
                report["total"], report["passed"], payload))


def save_comparison(bundle, path=None):
    saved = copy.deepcopy(bundle)
    saved["comparison_id"] = uuid.uuid4().hex
    saved["run_ids"] = {variant:uuid.uuid4().hex for variant in ("a","b")}
    for variant in ("a","b"):
        saved[variant]["comparison"] = {"id":saved["comparison_id"],"variant":variant.upper(),"label":saved["labels"][variant]}
    with connection(path) as db, db:
        for variant in ("a","b"):
            insert_run(db, saved["run_ids"][variant], saved[variant])
        db.execute("INSERT INTO comparisons VALUES (?, ?, ?, ?, ?)",
                   (saved["comparison_id"],saved["created_at"],saved["labels"]["a"],saved["labels"]["b"],
                    json.dumps(saved,ensure_ascii=False,allow_nan=False)))
    return saved


def list_comparisons(path=None, limit=100):
    with connection(path) as db:
        return [dict(row) for row in db.execute(
            "SELECT id, created_at, label_a, label_b FROM comparisons ORDER BY rowid DESC LIMIT ?", (limit,))]


def load_comparison(comparison_id, path=None):
    with connection(path) as db:
        row = db.execute("SELECT bundle_json FROM comparisons WHERE id = ?",(comparison_id,)).fetchone()
    if row is None:
        raise KeyError("Сравнение не найдено")
    return json.loads(row[0])


def list_runs(path=None, limit=200):
    with connection(path) as db:
        return [dict(row) for row in db.execute(
            "SELECT id, created_at, provider, model, total, passed FROM runs ORDER BY rowid DESC LIMIT ?",
            (limit,))]


def load_run(run_id, path=None):
    with connection(path) as db:
        row = db.execute("SELECT report_json FROM runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        raise KeyError("Запуск не найден")
    return json.loads(row[0])


def compare_runs(before, after):
    left = {case["id"]: case for case in before["results"]}
    right = {case["id"]: case for case in after["results"]}
    rows = []
    for case_id in dict.fromkeys([*left, *right]):
        old, new = left.get(case_id), right.get(case_id)
        if old is None:
            status = "Добавлен"
        elif new is None:
            status = "Удалён"
        elif any(old.get(key, default) != new.get(key, default) for key, default in
                 (("prompt", None), ("expected", None), ("check", "substring"), ("output_format", "text"), ("steps", None))):
            status = "Условия изменены"
        elif new.get("error"):
            status = "Техническая ошибка"
        elif old.get("error"):
            status = "Ошибка устранена"
        elif old["passed"] == new["passed"]:
            status = "Без изменений"
        else:
            status = "Исправлен" if new["passed"] else "Новый провал"
        rows.append({"id": case_id, "изменение": status,
                     "до": old["passed"] if old else None, "после": new["passed"] if new else None,
                     "ответ до": old.get("actual") if old else None,
                     "ответ после": new.get("actual") if new else None,
                     "ошибка до": old.get("error") if old else None,
                     "ошибка после": new.get("error") if new else None,
                     "время до, мс":old.get("latency_ms") if old else None,
                     "время после, мс":new.get("latency_ms") if new else None})
    return rows
