"""Риск заморозка + влажность/роса. Совместимо со старым API.

Старый API (восстановлен из __pycache__/freeze):
  estimate_t_in_no_heat(t_out_series, t_start=14.0, k_loss=0.35)
  hdd_deficit(t_in_series, t_crit=9.0)
  freeze_risk(hdd, a=0.045, b=-2.7)
  freeze_loss(p_freeze, area_m2, yield_kg_m2=10.0, price=300.0)

Новое (v2, для потолка):
  dew_point_magnus(T_c, RH_pct) -> °C
  condensation_flag(T_film, T_dew) -> bool
  disease_flag(RH_series, T_series) -> dict

Размерности: T °C, HDD градусо-часы, p 0-1, loss тенге.
Эвристика freeze_risk ТРЕБУЕТ полевой валидации (см. config.FREEZE_*).
"""
import math

try:
    from .config import T_CRIT_C, FREEZE_A, FREEZE_B, YIELD_KG_M2, PRICE_TG_KG
except ImportError:
    from config import T_CRIT_C, FREEZE_A, FREEZE_B, YIELD_KG_M2, PRICE_TG_KG


def _as_temp(t, t_crit_default=T_CRIT_C):
    """Принимает float или dict{T}. Возвращает float."""
    if isinstance(t, dict):
        return float(t.get("T", t_crit_default))
    return float(t)


def hdd_deficit(t_in_series, t_crit=T_CRIT_C):
    """HDD-дефицит: sum(max(0, t_crit - T_in)) по часам. Возврат градусо-часы."""
    s = 0.0
    for t in t_in_series:
        v = _as_temp(t, t_crit)
        if v < t_crit:
            s += (t_crit - v)
    return round(s, 2)


def freeze_risk(hdd, a=FREEZE_A, b=FREEZE_B):
    """Логистика p=1/(1+exp(-(a*HDD+b))). Эвристика, не калиброванная вероятность."""
    z = a * float(hdd) + b
    # клиппинг чтобы не переполнить exp
    z = max(min(z, 30.0), -30.0)
    p = 1.0 / (1.0 + math.exp(-z))
    return round(p, 3)


def freeze_loss(p_freeze, area_m2, yield_kg_m2=YIELD_KG_M2, price=PRICE_TG_KG):
    """Ожидаемые потери: p * площадь * урожай * цена. Тенге."""
    return round(float(p_freeze) * float(area_m2) * float(yield_kg_m2) * float(price), 0)


def estimate_t_in_no_heat(t_out_series, t_start=14.0, k_loss=0.35):
    """Экспоненциальное остывание без отопления (legacy, для совместимости).

    t[t+1] = t + k*(t_out - t). k_loss 0-1 за час.
    Возврат: список {time, T}. t_start — T внутри в 18:00.
    ВНИМАНИЕ: это грубая модель. Для потолка используй dynamics.simulate_no_heat.
    """
    out = []
    t = float(t_start)
    for r in t_out_series:
        t_out = float(r["T"]) if isinstance(r, dict) else float(r)
        t = t + float(k_loss) * (t_out - t)
        tm = r.get("time", "") if isinstance(r, dict) else ""
        out.append({"time": tm, "T": round(t, 2)})
    return out


def dew_point_magnus(t_c, rh_pct):
    """Точка росы по Магнусу (°C). T °C, RH 0-100."""
    rh = max(min(float(rh_pct), 100.0), 1.0)
    t = float(t_c)
    a, b = 17.625, 243.04
    h = math.log(rh / 100.0) + (a * t) / (b + t)
    td = b * h / (a - h)
    return round(td, 2)


def condensation_flag(t_film_c, t_dew_c):
    """True если пленка холоднее росы -> конденсат (+5-10% потерь)."""
    return float(t_film_c) < float(t_dew_c)


def disease_flag(rh_series, t_series, rh_thr=90.0, hours_thr=4):
    """Флаг риска гнили: RH>thr N часов подряд при T 12-22°C.

    Возврат {risk: bool, max_streak: int, note: str}.
    """
    streak = max_streak = 0
    for rh, t in zip(rh_series, t_series):
        if float(rh) >= rh_thr and 12.0 <= float(t) <= 22.0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    risk = max_streak >= hours_thr
    return {
        "risk": risk,
        "max_streak": max_streak,
        "note": "проветрить 10% (потери вырастут, болезнь упадет)" if risk else "норма",
    }
