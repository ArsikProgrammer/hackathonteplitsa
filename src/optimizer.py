"""Оптимизатор ночи: 3 профиля + EV-выбор. Потолок вместо 'топи всю ночь'.

Профили:
  P1 flat: держать T_target всю ночь
  P2 econight: T_low до 02:00, T_target 02-06 (пик мороза), T_low дальше
  P3 screen: T_target + термоэкран (U*0.6)

Для каждого: Q(t) -> E -> топливо(газ/уголь с качеством) -> cost + p_freeze*Loss.
J = cost_fuel + p_freeze*Loss -> min. Ограничение: T_min >= Tcrit+margin.

Возврат: {options:[{name, E_kwh, fuel, cost, p, loss, J, schedule}], best}.
p_freeze считается по остаточному HDD при профиле (если профиль держит T>=Tcrit,
HDD=0 -> p мал; если котел не тянет -> остаточный дефицит -> p растет).
"""
try:
    from .dynamics import heat_need_series, simulate_no_heat
    from .fuels import fuel_need, price_per_kwh, boiler_check
    from .freeze import hdd_deficit, freeze_risk, freeze_loss, estimate_t_in_no_heat
    from .config import (T_CRIT_CUCUMBER, T_CRIT_TOMATO, SAFETY_MARGIN_C, BOILER_KW_MAX,
                         FREEZE_A, FREEZE_B, SCREEN_FACTOR, SCREEN_COST_PER_NIGHT,
                         SCREEN_WORK_PER_NIGHT, SOIL_HA_W_PER_K)
except ImportError:
    from dynamics import heat_need_series, simulate_no_heat
    from fuels import fuel_need, price_per_kwh, boiler_check
    from freeze import hdd_deficit, freeze_risk, freeze_loss, estimate_t_in_no_heat
    from config import (T_CRIT_CUCUMBER, T_CRIT_TOMATO, SAFETY_MARGIN_C, BOILER_KW_MAX,
                        FREEZE_A, FREEZE_B, SCREEN_FACTOR, SCREEN_COST_PER_NIGHT,
                        SCREEN_WORK_PER_NIGHT, SOIL_HA_W_PER_K)

T_CRIT = {"cucumber": T_CRIT_CUCUMBER, "tomato": T_CRIT_TOMATO}


def _target_series(night_rows, t_target, t_low, peak_hours=(2, 3, 4, 5, 6)):
    """Построить целевой профиль econight по часам из time."""
    out = []
    for r in night_rows:
        try:
            hh = int(str(r.get("time", ""))[11:13])
        except Exception:
            hh = -1
        out.append(float(t_target) if hh in peak_hours else float(t_low))
    return out


def _residual_hdd(night_rows, target_list, t_crit, boiler_ok=True, q_short_frac=0.0):
    """Остаточный HDD: если профиль держится и котел тянет -> 0.

    Если котел не тянет (q_short_frac 0-1 непокрытой мощности), T_in проседает
    линейно: T_in = T_out + (T_targ-T_out)*(1-short). HDD по просадке.
    """
    hdd = 0.0
    for r, tt in zip(night_rows, target_list):
        t_out = float(r["T"]) if isinstance(r, dict) else float(r)
        t_in = t_out + (float(tt) - t_out) * (1.0 - float(q_short_frac))
        if t_in < t_crit:
            hdd += (t_crit - t_in)
    return round(hdd, 2)


def optimize_night(night_rows, length=50.0, width=30.0, height=4.0, material="film",
                   t_target=18.0, crop="cucumber", fuel="gas", coal_quality="good",
                   fouling=1.0, boiler_kw_max=BOILER_KW_MAX, area_m2=1500.0,
                   yield_kg_m2=10.0, price_tg_kg=300.0, tariff_gas=35.0,
                   screen_cost_night=None, screen_owned=False):
    """Главная функция. Возврат best + все 3 опции + расписание включения."""
    t_crit = float(T_CRIT.get(crop, 8.0))
    t_min_allowed = t_crit + float(SAFETY_MARGIN_C)
    t_low = max(t_min_allowed, float(t_target) - 4.0)
    n = len(night_rows) or 1
    # цена ночи экрана: аргумент > config; если уже куплен — только работа
    _scr = float(screen_cost_night) if screen_cost_night is not None else float(SCREEN_COST_PER_NIGHT)
    _scr_p3 = float(SCREEN_WORK_PER_NIGHT) if screen_owned else _scr

    profiles = {
        "P1_flat": [float(t_target)] * n,
        "P2_econight": _target_series(night_rows, t_target, t_low),
        "P3_screen": [float(t_target)] * n,
    }
    screen = {"P1_flat": 1.0, "P2_econight": 1.0, "P3_screen": float(SCREEN_FACTOR)}

    # почва: профиль без отопления (ночь стартует от цели). Посчасовой вклад:
    # почва теплее цели -> греет (вычитаем), холоднее -> забирает тепло (прибавляем).
    hA = float(SOIL_HA_W_PER_K) * (length * width) / 1500.0
    try:
        soil_rows = simulate_no_heat(night_rows, length, width, height, material,
                                     t_in_start=float(t_target))
        soil_T = [float(r["T_soil"]) for r in soil_rows]
        noheat_t_in = [float(r["T_in"]) for r in soil_rows]
    except Exception:
        soil_T = [None] * n
        noheat_t_in = [float(r["T"]) if isinstance(r, dict) else float(r) for r in night_rows]

    # риск «без отопления» — общий для всех профилей, база маржинального EV
    hdd_noheat = hdd_deficit(noheat_t_in, t_crit)
    p_noheat = freeze_risk(hdd_noheat)

    options = []
    for name, targ in profiles.items():
        if soil_T[0] is None:
            sg = 0.0
        else:
            sg = [hA * (ts - float(tt)) for ts, tt in zip(soil_T, targ)]
        need = heat_need_series(night_rows, targ, length, width, height, material,
                                u_screen_factor=screen[name],
                                soil_gain_W=sg)
        q_peak = max([q["Q_W"] for q in need]) / 1000.0 if need else 0.0
        e_kwh = sum(q["Q_W"] for q in need) / 1000.0  # dt=1ч
        chk = boiler_check(q_peak, boiler_kw_max)
        short = 0.0 if chk["feasible"] else min(0.9, 1.0 - boiler_kw_max / max(q_peak, 1e-9))
        hdd = _residual_hdd(night_rows, targ, t_crit, chk["feasible"], short)
        p = freeze_risk(hdd)
        loss_max = round(float(area_m2) * float(yield_kg_m2) * float(price_tg_kg), 0)
        ev_loss = round(float(p) * loss_max, 0)
        fn = fuel_need(e_kwh, fuel, coal_quality, fouling)
        # cost: единый источник fuel_need (fouling учтен).
        # газ: UI-тариф вместо config — пересчет qty*tariff.
        if fuel == "gas":
            cost = round(float(fn["qty"]) * float(tariff_gas), 0)
        else:
            cost = fn["cost_tg"]
        # P3: экран платный, иначе всегда best. Куплен — только работа.
        screen_fee = round(_scr_p3, 0) if name == "P3_screen" else 0.0
        cost = round(float(cost) + float(screen_fee), 0)
        J = round(float(cost) + float(ev_loss), 0)
        # расписание: первый час где Q>30% пика
        start = ""
        for q in need:
            if q["Q_W"] >= 0.3 * (q_peak * 1000.0) and q_peak > 0:
                start = q["time"]
                break
        options.append({
            "name": name, "E_kwh": round(e_kwh, 1), "Q_peak_kw": round(q_peak, 1),
            "fuel_qty": fn["qty"], "fuel_unit": fn["unit"], "cost_tg": cost,
            "hdd": hdd, "p_freeze": p, "p_noheat": p_noheat,
            "loss_max_tg": loss_max, "ev_loss_tg": ev_loss,
            "loss_tg": ev_loss, "J_tg": J, "screen_fee_tg": screen_fee,
            "boiler": chk["note"], "start_at": start,
            "t_min": round(min(targ), 1),
        })
    best = min(options, key=lambda o: o["J_tg"])
    saving = max(o["cost_tg"] for o in options) - best["cost_tg"]
    return {"options": options, "best": best, "saving_tg": round(saving, 0),
            "t_crit": t_crit, "crop": crop, "fuel": fuel,
            "p_noheat": p_noheat, "hdd_noheat": hdd_noheat}
