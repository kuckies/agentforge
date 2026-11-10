import json
import sqlite3
from pathlib import Path
import streamlit as st
from agents import LocalHTTPAgent, SupportHTTPAgent
from comparison_ui import render_comparison, render_comparison_history
from engine import run_suite
from help_ui import render_help
from history import save_run
from history_ui import render_history
from instructions import INSTRUCTIONS
from local_models import MODELS, ensure_model
from scenario_files import apply_upload, parse_scenarios


def render_testing():
    st.subheader("Проверьте ответы агента")
    st.caption("Выберите агента → выберите или загрузите задачи → запустите проверку")
    mode=st.selectbox("Агент",["Демо (бесплатно)","Локальная модель","Ollama (локально)","Бот поддержки (учебный)","Свой агент"])
    if mode=="Демо (бесплатно)":
        st.info("Первый запуск: оставьте демо и нажмите «Запустить тесты». Ожидаемый результат — 3/3.")
    elif mode=="Бот поддержки (учебный)":
        st.info("Откройте Start-TestBot.cmd и дождитесь запуска бота. Затем можно проверить одиночные обращения или диалоги.")
        st.markdown("[Открыть чат учебного бота](http://127.0.0.1:8085)")
        with st.expander("Подключение к боту"):
            endpoint=st.text_input("Адрес API бота","http://127.0.0.1:8085/v1/chat/completions",key="support_endpoint")
            timeout=st.number_input("Ожидание ответа, секунд",min_value=1,max_value=300,value=60)
    else:
        profile=st.selectbox("Локальная модель",list(MODELS)) if mode=="Локальная модель" else mode
        config=MODELS.get(profile,{"port":11434,"alias":"qwen2.5:1.5b"})
        own_protocol=st.selectbox("Протокол агента",["OpenAI-совместимый","Ollama"],key="own_protocol") if mode=="Свой агент" else None
        protocol="ollama" if mode=="Ollama (локально)" or own_protocol=="Ollama" else "openai"
        default_endpoint=(f'http://127.0.0.1:{config["port"]}/api/generate' if protocol=="ollama" else
                          f'http://127.0.0.1:{config["port"] if mode=="Локальная модель" else 8080}/v1/chat/completions')
        if mode=="Локальная модель":
            st.caption("Установленная модель запустится на время проверки. Уже запущенная останется работать.")
        else:
            st.caption("Сначала запустите сервер своего агента на этом ПК. Адрес и модель укажите ниже.")
        instruction_version=st.radio("Версия инструкции",list(INSTRUCTIONS),horizontal=True,key="instruction_version")
        if st.session_state.get("loaded_instruction")!=instruction_version:
            st.session_state["system_prompt"]=INSTRUCTIONS[instruction_version]
            st.session_state["loaded_instruction"]=instruction_version
        with st.expander("Инструкция и настройки подключения"):
            system=st.text_area("Инструкция агенту",key="system_prompt")
            endpoint=st.text_input("Адрес API",default_endpoint,key=f"endpoint-{profile}-{protocol}")
            model=st.text_input("Модель",config["alias"] if mode!="Свой агент" else "my-agent",key=f"model-{profile}-{protocol}")
            timeout=st.number_input("Ожидание ответа, секунд",min_value=1,max_value=300,value=60)
            st.caption("Поддерживаются локальные адреса с IP 127.0.0.1 или ::1. Пример запроса — на вкладке «Помощь».")
    run_slot=st.container()
    suite=(st.selectbox("Набор сценариев бота",["Отдельные обращения — 20","Диалоги — 10"],key="support_suite") if mode=="Бот поддержки (учебный)" else
           st.selectbox("Набор сценариев",["Быстрая проверка — 3","Практические задачи — 30","Контрольные задачи — 10"],key="suite") if mode!="Демо (бесплатно)" else "Демо")
    scenario_file=("scenarios.json" if mode=="Демо (бесплатно)" else
        ("scenarios-dialogues.json" if suite=="Диалоги — 10" else "scenarios-support.json") if mode=="Бот поддержки (учебный)" else
        "scenarios-practical.json" if suite=="Практические задачи — 30" else
        "scenarios-control.json" if suite=="Контрольные задачи — 10" else "scenarios-local.json")
    defaults=Path(__file__).with_name(scenario_file).read_text(encoding="utf-8")
    scope=(mode,suite)
    if st.session_state.get("scenario_mode")!=scope:
        st.session_state["scenarios"]=defaults
        st.session_state["scenario_mode"]=scope
        st.session_state.pop("scenario_import_fingerprint",None)
    nonce=st.session_state.get("upload_nonce",0)
    uploaded=st.file_uploader("Или загрузите свои сценарии",type=["json"],max_upload_size=1,
        key=f"scenario_upload:{mode}:{suite}:{nonce}",help="JSON в UTF-8, до 1 МБ. Загружайте сценарии, а не отчёт о запуске.")
    upload_error=False
    if uploaded is not None:
        try:
            imported=apply_upload(uploaded.getvalue(),st.session_state)
            st.success(f"Загружен файл {uploaded.name}: {len(imported)} сценариев")
        except ValueError as exc:
            st.error(str(exc))
            upload_error=True
    elif "scenario_import_fingerprint" in st.session_state:
        st.session_state.pop("scenario_import_fingerprint",None)
        st.session_state["scenarios"]=defaults
    with st.expander("Редактировать сценарии вручную"):
        source=st.text_area("Сценарии JSON — можно изменять",height=290,key="scenarios")
        st.caption('check=json проверяет содержимое; output_format=json отдельно включает JSON-режим модели.')
    try:
        preview=parse_scenarios(source.encode("utf-8"))
        st.caption(f'Сценариев: {len(preview)} · Шагов: {sum(len(c.get("steps",[c])) for c in preview)}')
        with st.expander("Посмотреть выбранные задачи"):
            st.dataframe([{"Сценарий":c["id"],"Вопрос":c.get("prompt",f'Диалог: {len(c.get("steps",[]))} шагов')} for c in preview],width="stretch")
        st.download_button("Скачать сценарии",json.dumps(preview,ensure_ascii=False,indent=2),file_name="agentforge-scenarios.json",mime="application/json",key="download_scenarios")
    except ValueError:
        st.caption("В тексте сценариев есть ошибка. При запуске будет показана её причина.")
    if run_slot.button("Запустить тесты",type="primary",key="run_tests",disabled=upload_error):
        st.session_state.pop("report",None)
        st.session_state.pop("saved_run",None)
        try:
            cases=parse_scenarios(source.encode("utf-8"))
            if any("steps" in case for case in cases) and mode!="Бот поддержки (учебный)":
                raise ValueError("Для диалоговых сценариев выберите «Бот поддержки (учебный)»")
            if mode=="Демо (бесплатно)":
                report=run_suite(cases)
            else:
                agent=SupportHTTPAgent(endpoint,timeout) if mode=="Бот поддержки (учебный)" else LocalHTTPAgent(endpoint,model,protocol,timeout,system)
                bar=st.progress(0,text="Запускаю проверку…")
                def execute():
                    return run_suite(cases,agent,progress=lambda done,total:bar.progress(done/total,text=f"Проверено {done} из {total}"))
                if mode=="Локальная модель" and endpoint==default_endpoint and model==config["alias"]:
                    with st.spinner("Подготавливаю модель и проверяю ответы…"),ensure_model(profile):
                        report=execute()
                else:
                    report=execute()
            st.session_state["report"]=report
            try:
                st.session_state["saved_run"]=save_run(report)
                st.session_state["history_run"]=st.session_state["saved_run"]
                st.success("Проверка завершена. Отчёт сохранён на вкладке «История».")
            except (OSError,sqlite3.Error) as exc:
                st.warning(f"Отчёт получен, но история не сохранена: {exc}")
        except (OSError,RuntimeError,ValueError) as exc:
            st.error(str(exc))
    def reload_examples():
        st.session_state["scenarios"]=defaults
        st.session_state.pop("scenario_import_fingerprint",None)
        st.session_state["upload_nonce"]=nonce+1
    st.button("Вернуть встроенный набор",key="load_examples",on_click=reload_examples)
    if "report" in st.session_state:
        report=st.session_state["report"]
        st.subheader("Результат последней проверки")
        st.metric("Пройдено",f'{report["passed"]} / {report["total"]}')
        errors=sum(bool(case["error"]) for case in report["results"])
        st.caption(f'Агент: {report.get("agent",{}).get("model",report["provider"])} · Технических ошибок: {errors}. Изменённые настройки применятся при следующем запуске.')
        if errors:
            st.warning("Есть ошибки подключения или выполнения. Откройте подробности ниже.")
        if any("steps" in case for case in report["results"]):
            st.caption(f'Шаги диалогов: {report["passed_steps"]} / {report["total_steps"]}. Каждый сценарий — новый разговор.')
            with st.expander("Ответы по шагам"):
                st.json([{"id":case["id"],"шаги":case.get("step_results",[])} for case in report["results"]])
        st.dataframe([{"Сценарий":c["id"],"Результат":"Ошибка" if c["error"] else "Пройден" if c["passed"] else "Не пройден", "Время, мс":c["latency_ms"]} for c in report["results"]],width="stretch")
        with st.expander("Подробные ответы и настройки"):
            st.json(report,expanded=False)
        st.download_button("Скачать JSON-отчёт",json.dumps(report,ensure_ascii=False,indent=2),file_name="agentforge-report.json",mime="application/json")


st.set_page_config(page_title="AgentForge",page_icon="🛠",layout="wide")
st.title("AgentForge")
st.caption("Проверяйте ответы агентов, сравнивайте варианты и сохраняйте результаты · 0.1.0-rc1")
testing,comparison,history,help_tab=st.tabs(["Проверка","Сравнение","История","Помощь"])
with testing:
    render_testing()
with comparison:
    render_comparison()
with history:
    render_history()
    render_comparison_history()
with help_tab:
    render_help()
