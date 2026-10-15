"""Топливо: газ + уголь с качеством. Цена за кВт*ч тепла, а не за кг.

Формулы:
  E_тепла[кВт*ч] = Q*N часов
  m/V_топлива = E / (LHV * eta * k_fouling)
  цена_кВтч = тариф / (LHV * eta * k_fouling)

LHV газ стабилен 9.3. Уголь 3.9-6.1 плавает с песком (кейс Шымкент-2023).
k_fouling 1.0 чистый -> 0.6 забитый. eta падает на малой нагрузке.
"""
try:
    from .config import (LHV_GAS, BOILER_ETA, GAS_TARIFF_TG_M3, COAL_TARIFF_TG_KG,
                         LHV_COAL_GOOD, LHV_COAL_POOR, ETA_COAL_GOOD, ETA_COAL_POOR)
except ImportError:
    from config import (LHV_GAS, BOILER_ETA, GAS_TARIFF_TG_M3, COAL_TARIFF_TG_KG,
                        LHV_COAL_GOOD, LHV_COAL_POOR, ETA_COAL_GOOD, ETA_COAL_POOR)


def price_per_kwh(fuel="gas", coal_quality="good", fouling=1.0):
    """тг/кВт*ч тепла. fuel: gas|coal. coal_quality: good|poor. fouling 0.5-1.0."""
    f = max(min(float(fouling), 1.0), 0.4)
    if fuel == "gas":
        return round(float(GAS_TARIFF_TG_M3) / (float(LHV_GAS) * float(BOILER_ETA) * f), 2)
    lhv = float(LHV_COAL_GOOD) if coal_quality == "good" else float(LHV_COAL_POOR)
    eta = float(ETA_COAL_GOOD) if coal_quality == "good" else float(ETA_COAL_POOR)
    return round(float(COAL_TARIFF_TG_KG) / (lhv * eta * f), 2)


def fuel_need(e_kwh, fuel="gas", coal_quality="good", fouling=1.0):
    """Сколько топлива на E кВт*ч. Возврат {qty, unit, cost_tg}."""
    f = max(min(float(fouling), 1.0), 0.4)
    e = max(float(e_kwh), 0.0)
    if fuel == "gas":
        v = e / (float(LHV_GAS) * float(BOILER_ETA) * f) if e > 0 else 0.0
        return {"qty": round(v, 1), "unit": "m3",
                "cost_tg": round(v * float(GAS_TARIFF_TG_M3), 0)}
    lhv = float(LHV_COAL_GOOD) if coal_quality == "good" else float(LHV_COAL_POOR)
    eta = float(ETA_COAL_GOOD) if coal_quality == "good" else float(ETA_COAL_POOR)
    m = e / (lhv * eta * f) if e > 0 else 0.0
    return {"qty": round(m, 1), "unit": "kg",
            "cost_tg": round(m * float(COAL_TARIFF_TG_KG), 0)}


def choose_fuel(e_kwh, fuel="gas", coal_quality="good", fouling=1.0):
    """Сравнение газ vs уголь для E. Возврат {gas:{}, coal:{}, cheapest}."""
    g = fuel_need(e_kwh, "gas", fouling=1.0)  # газ не зависит от угля
    c = fuel_need(e_kwh, "coal", coal_quality, fouling)
    cheapest = "gas" if g["cost_tg"] <= c["cost_tg"] else "coal"
    return {
        "gas": {**g, "price_kwh": price_per_kwh("gas")},
        "coal": {**c, "price_kwh": price_per_kwh("coal", coal_quality, fouling)},
        "cheapest": cheapest,
        "note": "уголь с песком дороже газа за тепло" if cheapest == "gas" and coal_quality == "poor" else "см. цену кВт*ч",
    }


def boiler_check(q_need_kw, q_max_kw, load_min_frac=0.3):
    """Проверка котла: хватит ли мощности + флаг низкой нагрузки (eta падает).

    Возврат {feasible, capped_kw, low_load, note}.
    """
    qn, qm = float(q_need_kw), float(q_max_kw)
    capped = min(qn, qm)
    feasible = qn <= qm
    low = (qn < load_min_frac * qm) if qm > 0 else False
    if not feasible:
        note = f"нужно {qn:.0f} кВт, котел {qm:.0f}: НЕ ТЯНЕТ, остаток -> риск"
    elif low:
        note = "нагрузка <30%: КПД -20%, лучше тактовать"
    else:
        note = "мощности хватает"
    return {"feasible": feasible, "capped_kw": round(capped, 1),
            "low_load": low, "note": note}
