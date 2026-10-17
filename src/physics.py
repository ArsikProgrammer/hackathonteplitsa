"""Тепловой баланс теплицы. Только код, без LLM.
Формула: Q = U*A*dT + 0.33*N*V*dT. Все размерности в docstring.
Точность без калибровки: +-15-30%, фиксируется открыто.
"""
import math

try:
    from .config import (U_VALUES, K_ROOF, LHV_GAS, BOILER_ETA, VENT_COEF,
                         GAS_TARIFF_TG_M3, AIR_EXCHANGE, WIND_CORRECTION)
except ImportError:
    from config import (U_VALUES, K_ROOF, LHV_GAS, BOILER_ETA, VENT_COEF,
                        GAS_TARIFF_TG_M3, AIR_EXCHANGE, WIND_CORRECTION)


def envelope_area(length, width, height, k_roof=K_ROOF):
    """Площадь ограждения, м2. Стены + крыша с поправкой."""
    walls = 2 * (length * height + width * height)
    roof = length * width * k_roof
    return walls + roof


def effective_n(base_n=AIR_EXCHANGE, wind=None):
    """Кратность воздухообмена с поправкой на ветер. Линейный рост от 4 м/с."""
    if wind is None:
        return base_n
    w = float(wind)
    if w <= 4.0:
        return base_n
    # +0.1 на каждый м/с сверх 4, потолок +0.8
    return base_n + min((w - 4.0) * 0.1, 0.8)


def heat_balance(length, width, height, material, t_in, t_out_series,
                 base_n=AIR_EXCHANGE, tariff=GAS_TARIFF_TG_M3):
    """Расчет за ночь по почасовому ряду наружной температуры.
    Вход: геометрия м, t_in °C, t_out_series список {T, wind}.
    Выход: словарь Q_kW средняя/пиковая, E_kWh, V_gas_m3, cost_tg, hours.
    Клиппинг U вне 2-8 с предупреждением.
    """
    U = U_VALUES.get(material, 6.2)
    clipped = False
    if not (2.0 <= U <= 8.0):
        U = min(max(U, 2.0), 8.0)
        clipped = True
    A = envelope_area(length, width, height)
    V = length * width * height
    hours = len(t_out_series) or 1
    qs = []
    for r in t_out_series:
        dT = t_in - float(r["T"])
        if dT <= 0:
            qs.append(0.0)
            continue
        n = effective_n(base_n, r.get("wind"))
        q = U * A * dT + VENT_COEF * n * V * dT  # Вт
        qs.append(q)
    q_avg = sum(qs) / len(qs) if qs else 0.0
    q_peak = max(qs) if qs else 0.0
    E_kwh = q_avg * hours / 1000.0
    v_gas = E_kwh / (LHV_GAS * BOILER_ETA) if E_kwh > 0 else 0.0
    cost = v_gas * tariff
    return {
        "U": U, "U_clipped": clipped, "A_env": round(A, 1), "V": round(V, 1),
        "Q_avg_kW": round(q_avg / 1000.0, 1), "Q_peak_kW": round(q_peak / 1000.0, 1),
        "E_kWh": round(E_kwh, 1), "V_gas_m3": round(v_gas, 1),
        "cost_tg": round(cost, 0), "hours": hours,
        "accuracy": "±15-30% без калибровки (табличный U)",
    }
