"""Динамика теплицы: 2 узла (воздух + почва). v2 для потолка.

Уравнения (ночь, Q_sun=0), dt=3600 c:
  C_air*dT_in/dt = Q_heat - G*(T_in-T_out) + hA*(T_soil-T_in) - Q_lat
  C_soil*dT_soil/dt = -hA*(T_soil-T_in) - k_deep*(T_soil-T_deep)
где G = U*A + 0.33*N*V [Вт/К] — полные потери, hA — связь с почвой [Вт/К].

Размерности: C Дж/К, Q Вт, T °C, dt c.
Калибровка: G и hA находятся Ridge по ночному остыванию (см. calibrate.py).
"""
try:
    from .physics import envelope_area, effective_n
    from .config import (U_VALUES, K_ROOF, VENT_COEF, AIR_EXCHANGE,
                         SOIL_C_KWH_PER_K, SOIL_HA_W_PER_K, C_AIR_KWH_PER_K,
                         T_DEEP_C, K_DEEP_W_PER_K)
except ImportError:
    from physics import envelope_area, effective_n
    from config import (U_VALUES, K_ROOF, VENT_COEF, AIR_EXCHANGE,
                        SOIL_C_KWH_PER_K, SOIL_HA_W_PER_K, C_AIR_KWH_PER_K,
                        T_DEEP_C, K_DEEP_W_PER_K)


def loss_coef(length, width, height, material, base_n=AIR_EXCHANGE, wind=None, u_override=None):
    """G = U*A + 0.33*N*V, Вт/К. u_override — калиброванное U."""
    from config import U_VALUES as _U
    try:
        from .config import U_VALUES as _U2
        _U = _U2
    except Exception:
        pass
    U = float(u_override) if u_override is not None else float(_U.get(material, 6.2))
    A = envelope_area(length, width, height)
    V = length * width * height
    n = effective_n(base_n, wind)
    G = U * A + VENT_COEF * n * V
    return {"G_W_per_K": round(G, 1), "U": U, "A": A, "V": V, "N": n}


def simulate_no_heat(t_out_series, length=50.0, width=30.0, height=4.0,
                     material="film", t_in_start=14.0, t_soil_start=16.0,
                     u_override=None, base_n=AIR_EXCHANGE):
    """Профиль остывания без отопления. Возврат список {time,T_in,T_soil}."""
    A_floor = float(length) * float(width)
    C_air_J = float(C_AIR_KWH_PER_K) * 3_600_000.0
    C_soil_J = float(SOIL_C_KWH_PER_K) * 3_600_000.0
    hA = float(SOIL_HA_W_PER_K) * A_floor / 1500.0  # нормировка на 1500 м2
    k_deep = float(K_DEEP_W_PER_K) * A_floor / 1500.0
    dt = 3600.0
    # подшаги для устойчивости явного Эйлера: dt_sub <= 0.4*C_air/(G+hA)
    t_in = float(t_in_start)
    t_soil = float(t_soil_start)
    out = []
    for r in t_out_series:
        t_out = float(r["T"]) if isinstance(r, dict) else float(r)
        wind = r.get("wind") if isinstance(r, dict) else None
        tm = r.get("time", "") if isinstance(r, dict) else ""
        G = loss_coef(length, width, height, material, base_n, wind, u_override)["G_W_per_K"]
        denom = max(G + hA, 1e-9)
        n_sub = max(1, int(dt / (0.4 * C_air_J / denom)) + 1)
        n_sub = min(n_sub, 60)
        h = dt / n_sub
        for _ in range(n_sub):
            dT_in = h / C_air_J * (-G * (t_in - t_out) + hA * (t_soil - t_in))
            dT_soil = h / C_soil_J * (-hA * (t_soil - t_in) - k_deep * (t_soil - float(T_DEEP_C)))
            t_in += dT_in
            t_soil += dT_soil
        out.append({"time": tm, "T_in": round(t_in, 2), "T_soil": round(t_soil, 2),
                    "T_out": round(t_out, 2)})
    return out


def heat_need_series(t_out_series, t_target_series, length=50.0, width=30.0,
                     height=4.0, material="film", base_n=AIR_EXCHANGE,
                     u_override=None, soil_gain_W=0.0, u_screen_factor=1.0):
    """Потребность Q_need(t) в Вт чтобы держать T_target(t).

    t_target_series: список float или dict{T}. soil_gain вычитается (тепло почвы).
    u_screen_factor 0.6 = термоэкран (U*0.6).
    Возврат список {time, Q_W, dT}.
    """
    out = []
    for i, r in enumerate(t_out_series):
        t_out = float(r["T"]) if isinstance(r, dict) else float(r)
        wind = r.get("wind") if isinstance(r, dict) else None
        tm = r.get("time", "") if isinstance(r, dict) else ""
        tt = t_target_series[i]
        t_targ = float(tt["T"]) if isinstance(tt, dict) else float(tt)
        dT = t_targ - t_out
        if dT <= 0:
            out.append({"time": tm, "Q_W": 0.0, "dT": round(dT, 2)})
            continue
        G = loss_coef(length, width, height, material, base_n, wind, u_override)["G_W_per_K"]
        G *= float(u_screen_factor)
        q = max(0.0, G * dT - float(soil_gain_W))
        out.append({"time": tm, "Q_W": round(q, 1), "dT": round(dT, 2)})
    return out
