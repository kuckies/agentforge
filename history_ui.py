import json
import sqlite3
import streamlit as st
from history import list_runs, load_run, compare_runs


def render_history():
    st.subheader("Сохранённые проверки")
    st.caption("Последние 200 запусков на этом ПК. Время в списке — UTC.")
    try:
        runs = list_runs()
        if not runs:
            st.info("Запустите первую проверку — её результат появится здесь автоматически.")
            return
        labels = {run["id"]:f'{run["created_at"]} · {run["model"]} · {run["passed"]}/{run["total"]} · {run["id"][:8]}' for run in runs}
        chosen = st.selectbox("Сохранённый запуск",list(labels),format_func=labels.get,key="history_run")
        saved = load_run(chosen)
        st.download_button("Скачать сохранённый отчёт",json.dumps(saved,ensure_ascii=False,indent=2),
                           file_name=f"agentforge-{chosen[:8]}.json",mime="application/json")
        st.dataframe(saved["results"],width="stretch")
        with st.expander("Настройки этого запуска"):
            st.json(saved.get("agent",{}))
        with st.expander("Все сохранённые запуски"):
            st.dataframe(runs,width="stretch")
        if len(runs)>1 and st.checkbox("Сравнить с другим запуском",key="history_compare"):
            baseline = st.selectbox("Сравнить с более ранним / другим запуском",list(labels),index=1,
                                    format_func=labels.get,key="history_baseline")
            if baseline != chosen:
                st.caption("До — второй выбранный запуск; после — запуск выше.")
                previous = load_run(baseline)
                st.dataframe(compare_runs(previous,saved),width="stretch")
                with st.expander("Настройки обоих запусков"):
                    st.json({"до":previous.get("agent",{}),"после":saved.get("agent",{})})
    except (OSError,sqlite3.Error,KeyError) as exc:
        st.error(f"Не удалось прочитать историю: {exc}")
