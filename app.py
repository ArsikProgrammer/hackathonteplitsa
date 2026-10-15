"""Теплица 0.15 га — ночной автопилот. 3 экрана, Apple-минимализм."""
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
from ai_assistant import verbalize_v2, anomaly_guard, price_verdict

st.set_page_config(page_title="Теплица 0.15 га — автопилот", layout="wide",
                   initial_sidebar_state="expanded")

st.markdown("""
<style>
.metric-card {
    background: linear-gradient(180deg, #1A1A1E 0%, #121214 100%);
    border: 1px solid #2A2A2E;
    border-radius: 16px;
    padding: 18px 20px;
    box-shadow: 0 8px 24px rgba(0,0,0,0.35);
}
.metric-card .label {
    font-size: 0.9rem;
    color: #9AA0A6;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-bottom: 6px;
}
.metric-card .value {
    font-size: 2.1rem;
    font-weight: 700;
    color: #FFFFFF;
    line-height: 1.1;
}
.action-heat { color: #FF6B35; }
.action-hold { color: #4CAF50; }
.action-sell { color: #9C27B0; }
.section-title {
    font-size: 1.35rem;
    font-weight: 600;
    color: #FFFFFF;
    margin-top: 30px;
    margin-bottom: 16px;
    letter-spacing: -0.02em;
}
.decision-box {
    background: linear-gradient(180deg, #1A1A1E 0%, #121214 100%);
    border: 1px solid #2A2A2E;
    border-radius: 20px;
    padding: 28px 32px;
    margin-top: 24px;
    box-shadow: 0 12px 32px rgba(0,0,0,0.4);
}
.decision-box h2 {
    font-size: 1.6rem;
    margin: 0 0 12px 0;
    color: #FFFFFF;
}
.decision-box .big {
    font-size: 3.4rem;
    font-weight: 800;
    line-height: 1.05;
}
.decision-box .sub {
    font-size: 1.05rem;
    color: #9AA0A6;
    margin-top: 10px;
}
.stTabs [data-baseweb="tab-list"] {
    gap: 8px;
    background: transparent;
}
.stTabs [data-baseweb="tab"] {
    background: #121214;
    border: 1px solid #2A2A2E;
    border-radius: 10px;
    color: #9AA0A6;
    font-weight: 500;
    padding: 10px 20px;
}
.stTabs [aria-selected="true"] {
    background: #FF6B35;
    color: #FFFFFF;
    border-color: #FF6B35;
}
div.stButton > button {
    background: #121214;
    border: 1px solid #2A2A2E;
    border-radius: 10px;
    color: #FFFFFF;
    font-weight: 500;
}
div.stButton > button:hover {
    border-color: #FF6B35;
}
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="section-title">Теплица 0.15 га — ночной автопилот</div>', unsafe_allow_html=True)
st.caption("Ночь: погода → тепло → деньги → решение. Неделя: цены + импорт → везти или держать.")

with st.sidebar:
    st.markdown('<div class="section-title" style="margin-top:0">Паспорт теплицы</div>', unsafe_allow_html=True)
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

    cols = st.columns(4)
    cards = [
        ("Топливо", f"{best['fuel_qty']} {best['fuel_unit']}", best["name"]),
        ("Затраты, тг", f"{best['cost_tg']:,.0f}", ""),
        ("Риск заморозка", f"{best['p_freeze']}", ""),
        ("Решение", {"heat": "ТОПИТЬ", "sell_early": "ПРОДАВАТЬ", "hold": "ДЕРЖАТЬ"}[d["action"]], d["action"]),
    ]
    for i, (label, value, extra) in enumerate(cards):
        action_class = ""
        if extra == "heat":
            action_class = "action-heat"
        elif extra == "hold":
            action_class = "action-hold"
        elif extra == "sell":
            action_class = "action-sell"
        cols[i].markdown(f"""
        <div class="metric-card">
            <div class="label">{label}</div>
            <div class="value {action_class}">{value}</div>
        </div>
        """, unsafe_allow_html=True)

    ev_txt = f"{d['ev_loss_tg']:,.0f}"
    cost_txt = f"{best['cost_tg']:,.0f}"
    screen_txt = f"{best.get('screen_fee_tg', 0):,.0f}"
    saving_txt = f"{res['saving_tg']:,.0f}"
    pstar_txt = f"{d['p_star']:.3f}"
    action_label = {"heat": "ТОПИТЬ", "sell_early": "ПРОДАВАТЬ", "hold": "ДЕРЖАТЬ"}[d["action"]]
    action_class = "action-heat" if d["action"] == "heat" else ("action-hold" if d["action"] == "hold" else "action-sell")

    st.markdown(f"""
    <div class="decision-box">
        <h2>{action_label} — профиль <span style="color:#FF6B35">{best['name']}</span></h2>
        <div class="big">{ev_txt}</div>
        <div class="sub">EV потерь {ev_txt} тг против затрат {cost_txt} тг (p*={pstar_txt}). Экран: {screen_txt} тг. Экономия: {saving_txt} тг/ночь.</div>
        <div class="sub" style="margin-top:10px">Котел: {best['boiler']}. Старт: {best['start_at']}. Причина: {d['reason']}</div>
    </div>
    """, unsafe_allow_html=True)

    rhs = [r.get("RH", 80) for r in base_rows]
    td = dew_point_magnus(min(r["T"] for r in base_rows), max(rhs))
    dz = disease_flag(rhs, [t_in] * len(rhs))
    st.caption(f"Роса ~{td}°C. Гниль: {'ДА — проветрить' if dz['risk'] else 'нет'}. Tcrit {t_crit}°C.")

    ag = anomaly_guard(float(best["fuel_qty"]), float(best["fuel_qty"]), best["p_freeze"])
    if ag["flag"]:
        st.warning(ag["note"])

    with st.expander("Все 3 профиля"):
        st.dataframe(pd.DataFrame(res["options"]), use_container_width=True)

    text, used = verbalize_v2(d, options=res["options"], farmer_text="")
    st.markdown('<div class="section-title">Решение текстом</div>', unsafe_allow_html=True)
    st.write(text)
    st.caption("LLM" if used else "Шаблон без LLM")

with tab2:
    st.markdown('<div class="section-title">Ценовой риск — experimental</div>', unsafe_allow_html=True)
    st.warning("p_dump — ИНДЕКС 0-1, не вероятность. Нужно ≥30 недель БНС. Сейчас TEMPLATE-12 строк.")
    p_dump, days = 0.0, 0
    pred_price = None
    try:
        from price_risk import load_dataset, train_ridge, dump_risk_from_model
        df = load_dataset(crop=crop)
        info = train_ridge(df)
        st.write(f"Строк: {info.get('n')}, статус: {info.get('status')}, MAE {info.get('mae')} vs lag {info.get('mae_lag')}")
        if info.get("status") == "ok":
            base_p = float(df.iloc[-1]["taraz_price"])
            pred_price = base_p
            r = dump_risk_from_model(pred_price, base_p)
            p_dump, days = r["p_dump"], r["days_to_dump"]
            st.write(r)
    except FileNotFoundError as e:
        st.caption(str(e))

    d2 = decide_ev(0, 0.0, 1, p_dump, days, readiness)
    action_label2 = {"heat": "ТОПИТЬ", "sell_early": "СОБРАТЬ РАНЬШЕ", "hold": "ЖДАТЬ"}[d2["action"]]
    action_class2 = "action-heat" if d2["action"] == "heat" else ("action-hold" if d2["action"] == "hold" else "action-sell")
    st.markdown(f"""
    <div class="metric-card">
        <div class="label">Совет по рынку</div>
        <div class="value {action_class2}">{action_label2}</div>
    </div>
    """, unsafe_allow_html=True)

    try:
        pv = price_verdict(
            float(df.iloc[-1]["taraz_price"]) if 'df' in locals() else 0.0,
            float(df.iloc[-1]["mean_price"]) if 'df' in locals() else 0.0,
            float(df.iloc[-1]["import_m"]) if 'df' in locals() and not pd.isna(df.iloc[-1]["import_m"]) else 0.0,
            p_dump, days, readiness)
        st.markdown(f"""
        <div class="metric-card">
            <div class="label">Импорт / рынок</div>
            <div class="value">{pv['text']}</div>
            <div class="sub">Дней до просадки: {pv['days_to_dump']}</div>
        </div>
        """, unsafe_allow_html=True)
    except Exception:
        pass

with tab3:
    st.markdown('<div class="section-title">Контрфакт 13–15.03.2024 (−11°C)</div>', unsafe_allow_html=True)
    try:
        hist = pd.read_csv("data/taraz_2024-03-13_15_real.csv")
        st.line_chart(hist.set_index("time")[["T"]], width='stretch')
        cold = hist[hist["T"] < -5].copy()
        night = cold.to_dict("records")
        night = [{"T": float(r["T"]), "wind": float(r.get("wind", 3)), "time": str(r["time"])} for r in night]
        hres = optimize_night(night, L, W, H, mat, t_in, crop, fuel,
                              coal_q, foul, boiler, L * W, YIELD_KG_M2, PRICE_TG_KG, tariff,
                              screen_cost_night=screen_cost, screen_owned=screen_owned)
        st.dataframe(pd.DataFrame(hres["options"]), width='stretch')
        st.success(f"best={hres['best']['name']}: {hres['best']['fuel_qty']} {hres['best']['fuel_unit']} / {hres['best']['cost_tg']:,.0f} тг")
    except Exception as e:
        st.error(f"Нет истории: {e}")

