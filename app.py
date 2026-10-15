"""Теплица 0.15 га — ночной автопилот. 3 экрана.
Запуск: streamlit run app.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import streamlit as st
import pandas as pd
from config import (DEMO_GREENHOUSE, T_TARGET_C, GAS_TARIFF_TG_M3, YIELD_KG_M2,
                    PRICE_TG_KG, T_CRIT_CUCUMBER, T_CRIT_TOMATO, BOILER_KW_MAX)
from weather import forecast_with_spread
from optimizer import optimize_night
from freeze import dew_point_magnus, disease_flag
from decision import decide_ev
from llm_verbalizer import verbalize
from ai_assistant import verbalize_v2, anomaly_guard, price_verdict

st.set_page_config(page_title="Теплица 0.15 га — автопилот", layout="wide")
st.title("Теплица 0.15 га — ночной автопилот")

with st.sidebar:
    st.header("Паспорт теплицы")
    L = st.number_input("Длина, м", value=DEMO_GREENHOUSE["length"])
    W = st.number_input("Ширина, м", value=DEMO_GREENHOUSE["width"])
    H = st.number_input("Высота, м", value=DEMO_GREENHOUSE["height"])
    mat = st.selectbox("Материал", ["film", "polycarbonate", "glass"], index=0)
    crop = st.selectbox("Культура", ["cucumber", "tomato"], index=0)
    t_in = st.number_input("Целевая T внутри, °C", value=T_TARGET_C)
    fuel = st.selectbox("Топливо", ["gas", "coal"], index=0)
    tariff = st.number_input("Тариф газа, тг/м3", value=GAS_TARIFF_TG_M3)
    coal_q = st.selectbox("Качество угля", ["good", "poor"], index=1)
    foul = st.slider("Состояние котла", 0.5, 1.0, 0.7)
    boiler = st.number_input("Мощность котла, кВт", value=BOILER_KW_MAX)
    readiness = st.slider("Готовность культуры", 0.0, 1.0, 0.85)
    screen_cost = st.number_input("Цена ночи экрана, тг", value=4000.0, step=100.0)
    screen_owned = st.checkbox("Экран уже куплен (только работа)", value=False)

t_crit = T_CRIT_CUCUMBER if crop == "cucumber" else T_CRIT_TOMATO
tab1, tab2, tab3 = st.tabs(["Ночь: топить?", "Неделя: продавать?", "История"])

with tab1:
    try:
        fc = forecast_with_spread()
        base_rows = fc["base"]
    except Exception as e:
        st.error(f"Прогноз недоступен: {type(e).__name__}. Демо-ночь -5C.")
        base_rows = [{"T": -5.0, "wind": 3.0, "RH": 85.0,
                      "time": f"2024-03-14T{h:02d}:00"} for h in (18, 19, 20, 21, 22, 23, 0, 1, 2, 3, 4, 5)]
        fc = {"base": base_rows}
    res = optimize_night(base_rows, L, W, H, mat, t_in, crop, fuel,
                         coal_q, foul, boiler, L * W,
                         YIELD_KG_M2, PRICE_TG_KG, tariff,
                         screen_cost_night=screen_cost, screen_owned=screen_owned)
    best = res["best"]
    d = decide_ev(best["cost_tg"], best["p_freeze"], best["loss_tg"],
                  0.0, 0, readiness, v_gas_m3=best["fuel_qty"], profile=best["name"])
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(f"Топливо ({best['name']})", f"{best['fuel_qty']} {best['fuel_unit']}")
    c2.metric("Затраты, тг", f"{best['cost_tg']:,.0f}")
    c3.metric("p_freeze", best["p_freeze"])
    c4.metric("Решение", {"heat": "ТОПИТЬ", "sell_early": "ПРОДАВАТЬ", "hold": "ДЕРЖАТЬ"}[d["action"]])
    st.caption(f"EV {d['ev_loss_tg']:,.0f} vs {best['cost_tg']:,.0f} (p*={d['p_star']}). "
               f"Экран: {best.get('screen_fee_tg',0):,.0f} тг. Экономия: {res['saving_tg']:,.0f} тг/ночь. "
               f"Котел: {best['boiler']}. Старт: {best['start_at']}.")
    rhs = [r.get("RH", 80) for r in base_rows]
    td = dew_point_magnus(min(r["T"] for r in base_rows), max(rhs))
    dz = disease_flag(rhs, [t_in] * len(rhs))
    st.caption(f"Роса ~{td}C. Гниль: {'ДА-проветрить' if dz['risk'] else 'нет'}. Tcrit {t_crit}C.")
    # сторожилка газа
    ag = anomaly_guard(float(best["fuel_qty"]), float(best["fuel_qty"]), best["p_freeze"])
    if ag["flag"]:
        st.warning(ag["note"])
    with st.expander("Все 3 профиля"):
        st.dataframe(pd.DataFrame(res["options"]))
    text, used = verbalize_v2(d, options=res["options"], farmer_text="")
    st.subheader("Решение текстом")
    st.write(text)
    st.caption("LLM" if used else "Шаблон без LLM")
    st.caption(f"Причина: {d['reason']}")

with tab2:
    st.subheader("Ценовой риск — experimental")
    st.warning("p_dump — ИНДЕКС 0-1, не вероятность. Нужно >=30 недель БНС. Сейчас TEMPLATE-12 строк.")
    p_dump, days = 0.0, 0
    pred_price = None
    try:
        from price_risk import load_dataset, train_ridge, dump_risk_from_model
        df = load_dataset(crop=crop)
        info = train_ridge(df)
        st.write(f"Строк: {info.get('n')}, статус: {info.get('status')}, MAE {info.get('mae')} vs lag {info.get('mae_lag')}")
        if info.get("status") == "ok":
            base_p = float(df.iloc[-1]["taraz_price"])
            # прогноз Ridge на следующую неделю (заглушка: текущая цена как базовый прогноз,
            # реальная модель обучается на >=30 недель)
            pred_price = base_p
            r = dump_risk_from_model(pred_price, base_p)
            p_dump, days = r["p_dump"], r["days_to_dump"]
            st.write(r)
    except FileNotFoundError as e:
        st.caption(str(e))
    d2 = decide_ev(0, 0.0, 1, p_dump, days, readiness)
    st.metric("Совет", {"heat": "ТОПИТЬ", "sell_early": "СОБРАТЬ РАНЬШЕ", "hold": "ЖДАТЬ"}[d2["action"]])
    # ИИ-конклюжн по импорту
    pv = price_verdict(float(df.iloc[-1]["taraz_price"]) if 'df' in locals() else 0.0,
                       float(df.iloc[-1]["mean_price"]) if 'df' in locals() else 0.0,
                       float(df.iloc[-1]["import_m"]) if 'df' in locals() and not pd.isna(df.iloc[-1]["import_m"]) else 0.0,
                       p_dump, days, readiness)
    st.caption(f"Импорт/рынок: {pv['text']} (дней до просадки: {pv['days_to_dump']})")

with tab3:
    st.subheader("Контрфакт 13-15.03.2024 (-11C)")
    try:
        hist = pd.read_csv("data/taraz_2024-03-13_15_real.csv")
        st.line_chart(hist.set_index("time")[["T"]])
        # честный срез -11C: строки 48-55 (15.03 00:00-07:00), а не 18:30 (там +3..-3C)
        cold = hist[hist["T"] < -5].copy()
        night = cold.to_dict("records")
        night = [{"T": float(r["T"]), "wind": float(r.get("wind", 3)), "time": str(r["time"])} for r in night]
        hres = optimize_night(night, L, W, H, mat, t_in, crop, fuel,
                              coal_q, foul, boiler, L * W, YIELD_KG_M2, PRICE_TG_KG, tariff,
                              screen_cost_night=screen_cost, screen_owned=screen_owned)
        st.dataframe(pd.DataFrame(hres["options"]))
        st.success(f"best={hres['best']['name']}: {hres['best']['fuel_qty']} {hres['best']['fuel_unit']} / {hres['best']['cost_tg']:,.0f} тг")
    except Exception as e:
        st.error(f"Нет истории: {e}")

