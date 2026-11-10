import json
from pathlib import Path
import sqlite3
import streamlit as st
from comparison import run_local_comparison
from history import list_comparisons, load_comparison
from instructions import INSTRUCTIONS
from local_models import MODELS
from scenario_files import parse_scenarios


def instruction_input(title, key, default):
    preset = st.selectbox(title,list(INSTRUCTIONS),index=default,key=key+"_preset")
    if st.session_state.get(key+"_loaded") != preset:
        st.session_state[key] = INSTRUCTIONS[preset]
        st.session_state[key+"_loaded"] = preset
    with st.expander("Изменить текст: "+title):
        text = st.text_area("Текст: "+title,key=key,height=120)
    if not text.strip():
        raise ValueError("Инструкция не должна быть пустой")
    return text, preset + (" (изменена)" if text != INSTRUCTIONS[preset] else "")


def render_comparison():
    st.subheader("Сравнить одной кнопкой")
    st.caption("Локальные модели выполнят один и тот же набор: сначала A, затем B. Остановленные установленные модели запустятся на время сравнения.")
    kind = st.radio("Что сравнить",["Инструкции одной модели","Две модели"],horizontal=True,key="compare_kind")
    run_slot=st.container()
    suites = {"Быстрая проверка — 3":"scenarios-local.json", "Практические задачи — 30":"scenarios-practical.json",
              "Контрольные задачи — 10":"scenarios-control.json"}
    suite = st.selectbox("Набор для сравнения",list(suites),index=1,key="compare_suite")
    cases = json.loads(Path(__file__).with_name(suites[suite]).read_text(encoding="utf-8"))
    uploaded=st.file_uploader("Или загрузите задачи для сравнения",type=["json"],max_upload_size=1,key=f"comparison_upload:{suite}")
    upload_error=False
    if uploaded is not None:
        try:
            cases=parse_scenarios(uploaded.getvalue())
            if any("steps" in case for case in cases):
                raise ValueError("Здесь сравниваются отдельные запросы. Диалоги проверяются на вкладке «Проверка»")
            st.success(f"Для обеих сторон загружено {len(cases)} сценариев")
        except ValueError as exc:
            st.error(str(exc))
            upload_error=True
    with st.expander("Одинаковые сценарии для A и B"):
        st.json(cases,expanded=False)
    ready = not upload_error
    try:
        if kind == "Инструкции одной модели":
            profile_a = profile_b = st.selectbox("Модель для обоих вариантов",list(MODELS),index=1,key="compare_single_model")
            instruction_a, name_a = instruction_input("Инструкция A","compare_instruction_a",0)
            instruction_b, name_b = instruction_input("Инструкция B","compare_instruction_b",1)
        else:
            profile_a = st.selectbox("Модель A",list(MODELS),index=1,key="compare_model_a")
            profile_b = st.selectbox("Модель B",list(MODELS),index=2,key="compare_model_b")
            instruction_a, name_a = instruction_input("Общая инструкция","compare_shared_instruction",1)
            instruction_b, name_b = instruction_a, name_a
    except ValueError as exc:
        st.warning(str(exc))
        ready = False
    if run_slot.button("Запустить сравнение",key="compare_run",type="primary",disabled=not ready):
        st.session_state.pop("comparison_result",None)
        state = st.empty()
        bar = st.progress(0,text="Подготавливаю сравнение…")
        try:
            with st.spinner("Выполняю оба варианта…"):
                result = run_local_comparison(cases,profile_a,instruction_a,profile_b,instruction_b,
                    f"{profile_a} · {name_a}",f"{profile_b} · {name_b}",
                    progress=lambda done,total:bar.progress(done/total,text=f"Выполнено {done} из {total} запросов"),
                    status=state.info)
            st.session_state["comparison_result"] = result
            st.session_state["comparison_history_id"] = result["comparison_id"]
            state.success("Оба отчёта и сравнение сохранены")
        except (OSError,RuntimeError,ValueError,KeyError,sqlite3.Error) as exc:
            state.error(f"Сравнение не завершено: {exc}")
    if "comparison_result" in st.session_state:
        result = st.session_state["comparison_result"]
        st.caption("Результат последнего сравнения; новые настройки применятся после следующего запуска.")
        columns = st.columns(2)
        for column,variant in zip(columns,("a","b")):
            data = result["summary"][variant]
            column.metric(f'{variant.upper()}: {result["labels"][variant]}',f'{data["passed"]}/{data["total"]}')
            column.caption(f'Медиана ответа: {data["median_latency_ms"]} мс; технических ошибок: {data["technical_errors"]}')
        st.write(f'Исправлено: {result["summary"]["improved"]}. Новых провалов: {result["summary"]["regressed"]}.')
        if any(result["summary"][variant]["technical_errors"] for variant in ("a","b")):
            st.warning("Есть технические ошибки. Они отмечены отдельно и не считаются улучшением качества ответов.")
        st.caption("Время включает прогрев и зависит от кэша и нагрузки ПК; это ориентир для этих запросов.")
        st.dataframe(result["changes"],width="stretch")
        st.download_button("Скачать сравнение и оба отчёта",json.dumps(result,ensure_ascii=False,indent=2),
                           file_name="agentforge-comparison.json",mime="application/json",key="download_comparison")


def render_comparison_history():
    st.subheader("История сравнений")
    try:
        comparisons = list_comparisons()
        if not comparisons:
            st.caption("Здесь появятся выполненные сравнения.")
        else:
            labels = {row["id"]:f'{row["created_at"]} · {row["label_a"]} → {row["label_b"]} · {row["id"][:8]}' for row in comparisons}
            selected = st.selectbox("Сохранённое сравнение",list(labels),format_func=labels.get,key="comparison_history_id")
            saved = load_comparison(selected)
            st.json(saved["summary"],expanded=False)
            st.dataframe(saved["changes"],width="stretch")
            st.download_button("Скачать сохранённое сравнение",json.dumps(saved,ensure_ascii=False,indent=2),
                file_name=f"agentforge-comparison-{selected[:8]}.json",mime="application/json",key="download_saved_comparison")
            with st.expander("Параметры сохранённого сравнения"):
                st.json({variant:saved[variant].get("agent",{}) for variant in ("a","b")})
    except (OSError,sqlite3.Error,KeyError) as exc:
        st.error(f"Не удалось прочитать сравнения: {exc}")
