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
from dynamics import simulate_no_heat
from freeze import dew_point_magnus, disease_flag
from decision import decide_ev, decide_price
from ai_assistant import (verbalize_v2, anomaly_guard, price_verdict,
                          extract_farm_state)

st.set_page_config(page_title="Теплица 0.15 га — автопилот", layout="wide",
                   initial_sidebar_state="expanded")

st.markdown("""
<style>
@keyframes fadeUp { from { opacity: 0; transform: translateY(14px); } to { opacity: 1; transform: translateY(0); } }
@keyframes glowPulse { 0%,100% { text-shadow: 0 0 18px rgba(255,138,91,.40); } 50% { text-shadow: 0 0 36px rgba(255,138,91,.85); } }
.stApp {
    background:
        radial-gradient(900px 520px at 88% -8%, rgba(255,138,91,.16), transparent 60%),
        radial-gradient(820px 520px at -12% 18%, rgba(80,190,255,.13), transparent 60%),
        radial-gradient(760px 760px at 50% 112%, rgba(160,90,255,.11), transparent 60%),
        linear-gradient(135deg, #0a0c16 0%, #10142a 46%, #171026 100%);
    background-attachment: fixed;
    color: #EDEFF3;
}
.hero-title {
    font-size: 2.6rem; font-weight: 800; letter-spacing: -0.03em; margin-bottom: 2px;
    background: linear-gradient(92deg, #FFB08A 0%, #FFD9A8 35%, #9BE8D8 70%, #8AB8FF 100%);
    -webkit-background-clip: text; background-clip: text; color: transparent;
    animation: fadeUp .6s ease both;
}
.hero-sub { font-size: 1.05rem; color: #A7AEBE; margin: 2px 0 20px 0; animation: fadeUp .7s ease both; }
.metric-card {
    background: linear-gradient(160deg, rgba(255,255,255,.075), rgba(255,255,255,.028));
    backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px);
    border: 1px solid rgba(255,255,255,.10);
    border-radius: 22px; padding: 20px 24px;
    box-shadow: 0 18px 44px rgba(0,0,0,.45), inset 0 1px 0 rgba(255,255,255,.08);
    transition: transform .25s ease, box-shadow .25s ease, border-color .25s ease;
    animation: fadeUp .55s ease both;
}
.metric-card:hover {
    transform: translateY(-3px);
    border-color: rgba(255,176,138,.45);
    box-shadow: 0 26px 60px rgba(255,138,91,.15), 0 18px 44px rgba(0,0,0,.5);
}
.metric-card .label { font-size: .82rem; color: #9AA3B8; text-transform: uppercase; letter-spacing: .09em; margin-bottom: 8px; }
.metric-card .value { font-size: 2.15rem; font-weight: 750; color: #FFFFFF; line-height: 1.12; }
.metric-card .sub { font-size: .95rem; color: #A7AEBE; margin-top: 8px; }
.action-heat { background: linear-gradient(92deg,#FF8A5B,#FFC56E); -webkit-background-clip: text; background-clip: text; color: transparent; animation: glowPulse 3.2s ease-in-out infinite; }
.action-hold { background: linear-gradient(92deg,#7CE0C3,#5BB8FF); -webkit-background-clip: text; background-clip: text; color: transparent; }
.action-sell { background: linear-gradient(92deg,#C77DFF,#FF9CEE); -webkit-background-clip: text; background-clip: text; color: transparent; }
.action-warn { background: linear-gradient(92deg,#FFD166,#FF9F68); -webkit-background-clip: text; background-clip: text; color: transparent; font-weight: 650; }
.decision-box {
    background: linear-gradient(160deg, rgba(255,255,255,.08), rgba(255,255,255,.03));
    backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px);
    border: 1px solid rgba(255,255,255,.11);
    border-radius: 24px; padding: 28px 32px; margin-top: 24px;
    box-shadow: 0 22px 56px rgba(0,0,0,.5), inset 0 1px 0 rgba(255,255,255,.09);
    animation: fadeUp .6s ease both;
}
.decision-box h2 { font-size: 1.6rem; margin: 0 0 12px 0; color: #FFFFFF; }
.decision-box .big { font-size: 3.2rem; font-weight: 800; line-height: 1.05;
    background: linear-gradient(92deg,#FFB08A,#FFD9A8); -webkit-background-clip: text; background-clip: text; color: transparent; }
.decision-box .sub { font-size: 1.02rem; color: #A7AEBE; margin-top: 10px; }
.stTabs [data-baseweb="tab-list"] { gap: 10px; background: transparent; }
.stTabs [data-baseweb="tab"] {
    background: rgba(255,255,255,.05); border: 1px solid rgba(255,255,255,.09);
    border-radius: 14px; color: #B9C0D0; font-weight: 550; padding: 10px 22px;
    transition: all .22s ease;
}
.stTabs [data-baseweb="tab"]:hover { border-color: rgba(255,176,138,.5); color: #FFD9C4; }
.stTabs [aria-selected="true"] {
    background: linear-gradient(92deg, #FF8A5B, #FFB08A);
    color: #14161F; border-color: transparent;
    box-shadow: 0 8px 26px rgba(255,138,91,.35);
}
div.stButton > button {
    background: rgba(255,255,255,.06); border: 1px solid rgba(255,255,255,.12);
    border-radius: 12px; color: #F0F2F7; font-weight: 550; transition: all .2s ease;
}
div.stButton > button:hover { border-color: #FF8A5B; box-shadow: 0 6px 20px rgba(255,138,91,.25); transform: translateY(-1px); }
div[data-testid="stImage"] img { border-radius: 20px; box-shadow: 0 24px 60px rgba(0,0,0,.55), 0 0 0 1px rgba(255,255,255,.08); }
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="hero-title">Теплица 0.15 га — ночной автопилот</div>', unsafe_allow_html=True)
st.markdown('<div class="hero-sub">Ночь: погода → тепло → деньги → решение. Неделя: ML-прогноз цены → ждать или везти. Логистика: куда везти и на чём.</div>', unsafe_allow_html=True)

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
    st.markdown("### Урожай")
    yld = st.number_input("Урожайность, кг/м²", value=YIELD_KG_M2, step=0.5)
    harvest_kg = st.number_input("Сбор, кг/день", value=300.0, step=10.0, min_value=0.0)
    shelf_days = st.number_input("Срок хранения, дней", value=5.0, step=1.0, min_value=1.0)
    marketable = st.slider("Товарный вид, %", 50, 100, 90)
    fact_gas = st.number_input("Фактический газ за ночь, м³ (0 — не мерил)",
                               value=0.0, step=1.0, min_value=0.0)
    farmer_text = st.text_input("Слова фермера (топливо/котёл/культура)", "")

# «Уши»: слова фермера переопределяют паспорт (LLM или keyword-фолбэк)
if farmer_text.strip():
    farm_params, farm_meta = extract_farm_state(farmer_text)
    crop = farm_params.get("crop") or crop
    fuel = farm_params.get("fuel") or fuel
    coal_q = farm_params.get("coal_quality") or coal_q
    if farm_params.get("fouling") is not None:
        foul = float(farm_params["fouling"])
    if farm_params.get("readiness") is not None:
        readiness = float(farm_params["readiness"])
    with st.sidebar:
        st.caption(f"Распознано ({farm_meta.get('source')}): {farm_params}")

t_crit = T_CRIT_CUCUMBER if crop == "cucumber" else T_CRIT_TOMATO

# ============ ОБЩИЙ РАСЧЁТ (один раз на ререндер, переиспользуется вкладками) ============
# 1) НОЧЬ
try:
    fc = forecast_with_spread()
    base_rows = fc["base"]
    weather_note = ("погода: ансамбль open-meteo" if fc["source"] == "ensemble"
                    else "погода: open-meteo, одиночный прогноз")
except Exception as e:
    weather_note = f"нет сети — демо-ночь −5°C ({type(e).__name__})"
    base_rows = [{"T": -5.0, "wind": 3.0, "RH": 85.0,
                  "time": f"2024-03-14T{h:02d}:00"} for h in (18, 19, 20, 21, 22, 23, 0, 1, 2, 3, 4, 5)]
res = optimize_night(base_rows, L, W, H, mat, t_in, crop, fuel,
                     coal_q, foul, boiler, L * W,
                     yld, PRICE_TG_KG, tariff,
                     screen_cost_night=screen_cost, screen_owned=screen_owned)
best = res["best"]
d = decide_ev(best["cost_tg"], best["p_freeze"], best["loss_tg"],
              0.0, 0, readiness, v_gas_m3=best["fuel_qty"],
              profile=best["name"], p_noheat=res["p_noheat"])
ACTION_RU_CARD = {"heat": "ТОПИТЬ", "sell_early": "ПРОДАВАТЬ", "hold": "ДЕРЖАТЬ"}

# 2) НЕДЕЛЯ (ML: месячная модель приоритет, иначе недельная)
ml_info, ml_df, ml_ds = None, None, "нет данных"
ml_pump = {"p_dump": 0.0, "days": 0, "pred": None, "base": 0.0,
           "mean": 0.0, "imp": 0.0, "risk": None}
try:
    from price_risk import load_dataset, train_ridge, dump_risk_from_model
    for csv_path, label in (("data/prices_monthly.csv", "месячная (2022-2026)"),
                            (None, "недельная (2026)")):
        try:
            cand = load_dataset(csv_path=csv_path, crop=crop)
            cand_info = train_ridge(cand)
            ml_info, ml_df, ml_ds = cand_info, cand, label
            if cand_info.get("status") == "ok":
                break
        except FileNotFoundError:
            continue
    if ml_info is not None:
        ml_pump["base"] = float(ml_df.iloc[-1]["taraz_price"])
        ml_pump["mean"] = float(ml_df.iloc[-1]["mean_price"])
        if "import_m" in ml_df.columns and not pd.isna(ml_df.iloc[-1]["import_m"]):
            ml_pump["imp"] = float(ml_df.iloc[-1]["import_m"])
        if ml_info.get("status") == "ok" and ml_info.get("pred_next"):
            ml_pump["pred"] = float(ml_info["pred_next"])
            rr = dump_risk_from_model(ml_pump["pred"], ml_pump["base"])
            ml_pump["p_dump"], ml_pump["days"] = rr["p_dump"], rr["days_to_dump"]
            ml_pump["risk"] = rr
except Exception:
    pass
week_dp = decide_price(ml_pump["base"], ml_pump["mean"], ml_pump["imp"],
                       ml_pump["p_dump"], ml_pump["days"], readiness)

# 3) ЛОГИСТИКА (дефолтная машина для сводки; параметры — во вкладке)
log_top = None
try:
    from logistics import rank_cities
    ldef = rank_cities(crop=crop)  # кэш после первого вызова
    log_top = ldef["rows"][0] if ldef["rows"] else None
except Exception:
    pass

tab1, tab2, tab3, tab4 = st.tabs(["Ночь: топить?", "Неделя: продавать?",
                                  "История", "Куда везти"])

# ============ ГЕРОЙ: быстрая сводка + 3D-разрез ============
st.markdown("## Сегодня")
h1, h2 = st.columns([3, 2], gap="large")
with h1:
    night_cls = "action-heat" if d["action"] == "heat" else "action-hold"
    ok_week = ml_info is not None and ml_info.get("status") == "ok" and ml_pump["pred"]
    week_val = "СОБРАТЬ РАНЬШЕ" if week_dp["sell_early"] else "ЖДАТЬ"
    revenue_day = (ml_pump['pred'] * harvest_kg * marketable / 100.0) if ok_week else 0.0
    week_line = (f"прогноз {ml_pump['pred']:,.0f} тг vs сейчас {ml_pump['base']:,.0f} тг "
                 f"({ml_ds}) · выручка за день сбора ≈ {revenue_day:,.0f} тг · окно хранения {shelf_days:.0f} дн"
                 if ok_week
                 else "модель experimental — вердикт по цене не подаём (честно)")
    log_line = (f"{log_top['city']}: +{log_top['margin_kg']:.0f} тг/кг, {log_top['km']} км "
                f"(для дефолтной машины 22 л/100км)" if log_top else "нет региональных данных")
    boiler_warn = (' <span class="action-warn">· ⚠ котёл не тянет</span>'
                   if "НЕ ТЯНЕТ" in str(best.get("boiler", "")) else "")
    ev_line = (f"без котла риск {res['p_noheat']} (EV {res['p_noheat'] * best['loss_max_tg']:,.0f} тг) "
               f"→ с профилем {best['p_freeze']} (EV {best['ev_loss_tg']:,.0f} тг)")
    st.markdown(f"""
    <div class="metric-card">
        <div class="label">Ночь — {weather_note}</div>
        <div class="value {night_cls}">{ACTION_RU_CARD.get(d['action'], d['action'])}</div>
        <div class="sub">профиль {best['name']} · {best['fuel_qty']} м³ · {best['cost_tg']:,.0f} тг (газ+экран){boiler_warn}</div>
        <div class="sub">{ev_line}</div>
    </div>
    <div style="height:12px"></div>
    <div class="metric-card">
        <div class="label">Неделя — цена огурца</div>
        <div class="value">{'<span class="action-sell">' if week_dp['sell_early'] else '<span class="action-hold">'}{week_val}</span></div>
        <div class="sub">{week_line}</div>
    </div>
    <div style="height:12px"></div>
    <div class="metric-card">
        <div class="label">Куда везти</div>
        <div class="value">{log_top['city'] if log_top else '—'}</div>
        <div class="sub">{log_line}</div>
    </div>
    """, unsafe_allow_html=True)
with h2:
    st.image("assets/greenhouse3d.png")
    st.caption("Теплица 0.15 га в разрезе: ночью холод снаружи, тепло — котёл + почва. "
               "Рендер генерируется кодом (tools/render_greenhouse3d.py).")

with tab1:
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
        elif extra == "sell_early":
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
        <h2>{action_label} — профиль <span style="color:#FF8A5B">{best['name']}</span></h2>
        <div class="big">{ev_txt}</div>
        <div class="sub">Экономия EV {ev_txt} тг против затрат {cost_txt} тг = газ {best['fuel_qty']} м³ × {tariff} тг + экран {screen_txt} тг (p*={pstar_txt}). Экономия профиля: {saving_txt} тг/ночь.</div>
        <div class="sub" style="margin-top:10px">Котел: {best['boiler']}. Старт: {best['start_at']}. Причина: {d['reason']}</div>
    </div>
    """, unsafe_allow_html=True)

    rhs = [r.get("RH", 80) for r in base_rows]
    td = dew_point_magnus(min(r["T"] for r in base_rows), max(rhs))
    try:
        prof_noheat = simulate_no_heat(base_rows, L, W, H, mat, t_in_start=t_in)
        t_in_series = [r["T_in"] for r in prof_noheat]
    except Exception:
        t_in_series = [t_in] * len(rhs)
    dz = disease_flag(rhs, t_in_series)
    st.caption(f"Роса ~{td}°C. Гниль: {'ДА — проветрить' if dz['risk'] else 'нет'}. Tcrit {t_crit}°C.")

    if fact_gas > 0:
        ag = anomaly_guard(float(fact_gas), float(best["fuel_qty"]), best["p_freeze"])
        if ag["flag"]:
            st.warning(ag["note"])
        else:
            st.success(f"Факт {fact_gas} м³ — в пределах модели (±30%).")
    else:
        st.caption("Фактический газ не введён — «сторожилка» не проверяет модель.")

    with st.expander("Все 3 профиля"):
        st.dataframe(pd.DataFrame(res["options"]), width='stretch')

    text, used = verbalize_v2(d, options=res["options"], farmer_text="")
    st.markdown('<div class="section-title">Решение текстом</div>', unsafe_allow_html=True)
    st.write(text)
    st.caption("LLM" if used else "Шаблон без LLM")

with tab2:
    st.markdown('<div class="section-title">Ценовой риск — Ridge (ML)</div>', unsafe_allow_html=True)
    st.caption("p_dump — индекс 0-1, не вероятность (калибровка Platt в планах). Обучение: месячные цены Тараза 2022-2026.")
    if ml_info is not None:
        st.write(f"Модель: {ml_ds} | строк: {ml_info.get('n')}, статус: {ml_info.get('status')}, "
                 f"MAE {ml_info.get('mae')} vs лаг {ml_info.get('mae_lag')}, "
                 f"прогноз: {ml_info.get('pred_next')}")
        if ml_pump.get("risk"):
            st.write(ml_pump["risk"])
        else:
            st.caption("Ни одна модель не побила базлайн — индекс риска не считается (честно).")
    else:
        st.caption("Датасеты цен не найдены (prices_monthly/weekly.csv).")

    # недельное решение: только sell_early/hold, «топить» на этом экране невозможно
    dp = week_dp
    action_label2 = {"sell_early": "СОБРАТЬ РАНЬШЕ", "hold": "ЖДАТЬ"}[dp["action"]]
    action_class2 = "action-sell" if dp["sell_early"] else "action-hold"
    st.markdown(f"""
    <div class="metric-card">
        <div class="label">Совет по рынку</div>
        <div class="value {action_class2}">{action_label2}</div>
        <div class="sub">{dp['reason']}</div>
    </div>
    """, unsafe_allow_html=True)

    pv = price_verdict(ml_pump["base"], ml_pump["mean"], ml_pump["imp"],
                       ml_pump["p_dump"], ml_pump["days"], readiness)
    st.markdown(f"""
    <div class="metric-card">
        <div class="label">Импорт / рынок</div>
        <div class="value">{pv['text']}</div>
        <div class="sub">Дней до просадки: {pv['days_to_dump']}</div>
    </div>
    """, unsafe_allow_html=True)

with tab3:
    st.markdown('<div class="section-title">Контрфакт 13–15.03.2024 (−11°C)</div>', unsafe_allow_html=True)
    try:
        hist = pd.read_csv("data/taraz_2024-03-13_15_real.csv")
        st.line_chart(hist.set_index("time")[["T"]], width='stretch')
        hrs = hist["time"].astype(str).str[11:13].astype(int)
        night = hist[(hrs >= 18) | (hrs <= 6)].to_dict("records")
        night = [{"T": float(r["T"]), "wind": float(r.get("wind", 3)), "time": str(r["time"])} for r in night]
        hres = optimize_night(night, L, W, H, mat, t_in, crop, fuel,
                              coal_q, foul, boiler, L * W, yld, PRICE_TG_KG, tariff,
                              screen_cost_night=screen_cost, screen_owned=screen_owned)
        st.dataframe(pd.DataFrame(hres["options"]), width='stretch')
        st.success(f"best={hres['best']['name']}: {hres['best']['fuel_qty']} {hres['best']['fuel_unit']} / {hres['best']['cost_tg']:,.0f} тг")
    except Exception as e:
        st.error(f"Нет истории: {e}")

with tab4:
    st.markdown('<div class="section-title">Логистика: куда везти (твоя машина)</div>',
                unsafe_allow_html=True)
    st.caption("Введи параметры своего транспорта — посчитает чистую маржу по 19 городам "
               "и построит маршрут. Допущения: дорога = прямая×1.25, 70 км/ч, возврат порожняком.")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        log_cons = st.number_input("Расход, л/100 км", value=22.0, step=0.5, min_value=5.0)
    with c2:
        log_cap = st.number_input("Вместимость, тонн",
                                  value=max(round(harvest_kg / 1000.0, 1), 0.3),
                                  step=0.5, min_value=0.3)
    with c3:
        log_fuel = st.number_input("Цена топлива, тг/л", value=280.0, step=5.0)
    with c4:
        log_drv = st.number_input("Водитель, тг/сутки", value=15000.0, step=1000.0)
    c5, c6 = st.columns(2)
    with c5:
        log_ref = st.checkbox("Рефрижератор (+2.5 л/ч)", value=True)
    with c6:
        log_days = st.slider("Суток на рейс", 1, 7, 3)
    try:
        from logistics import rank_cities, greedy_route
        lout = rank_cities(crop=crop, capacity_kg=log_cap * 1000.0,
                           consum_l100=log_cons, fuel_price=log_fuel,
                           ref=log_ref, driver_pay_per_day=log_drv)
        m = lout["month"]
        st.write(f"Цены: {m[1]:02d}.{m[0]} | цена дома (Тараз): {lout['home']:.0f} тг/кг | "
                 f"машина: {log_cons} л/100км, {log_cap} т, реф={'да' if log_ref else 'нет'}")
        df_log = pd.DataFrame(lout["rows"]).rename(columns={
            "city": "Город", "price": "Цена_тгкг", "km": "Дорога_км",
            "trip_tg": "Рейс_туда+обратно_тг", "cost_kg": "Себестоимость_тгкг",
            "margin_kg": "Маржа_тгкг", "margin_trip_tg": "Маржа_за_рейс_тг"})
        st.dataframe(df_log, width='stretch', hide_index=True)
        route = greedy_route(lout["rows"], log_days, capacity_kg=log_cap * 1000.0)
        if route["legs"]:
            path = " → ".join(["Тараз"] + [x["city"] for x in route["legs"]] + ["Тараз"])
            st.markdown(f"""
            <div class="metric-card">
                <div class="label">Лучший маршрут на {log_days} суток</div>
                <div class="value">{path}</div>
                <div class="sub">{route['total_km']} км, ~{route['days_used']} суток в пути,
                маржа ≈ {route['margin_tg']:,.0f} тг (маржа считается консервативно)</div>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.warning("При таких расходах ни один город не даёт положительной маржи — держать дома.")
    except Exception as e:
        st.error(f"Логистика: {type(e).__name__}: {e}")

