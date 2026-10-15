"""Pareto-front: 100 tochek moshchnosti. Legacy API sohranen + t_crit param."""
import numpy as np
try:
    from .physics import envelope_area, effective_n
    from .config import (U_VALUES, LHV_GAS, BOILER_ETA, VENT_COEF,
                         GAS_TARIFF_TG_M3, T_CRIT_CUCUMBER)
    from .freeze import freeze_risk
    from .decision import margin
except ImportError:
    from physics import envelope_area, effective_n
    from config import (U_VALUES, LHV_GAS, BOILER_ETA, VENT_COEF,
                        GAS_TARIFF_TG_M3, T_CRIT_CUCUMBER)
    from freeze import freeze_risk
    from decision import margin


def simulate(length, width, height, material, t_in, t_out_night,
             boiler_kw_max, y_kg, price, drop_frac,
             tariff=GAS_TARIFF_TG_M3, t_crit=T_CRIT_CUCUMBER):
    """t_out_night: [{T, wind}]. Vozvrat {q_need_kw, boiler_kw_max, points}.

    Ispravlenie v2: t_crit parametr vmesto hardkoda 9.0.
    Mertvaya deficit_scale udalena.
    """
    U = U_VALUES.get(material, 6.2)
    A = envelope_area(length, width, height)
    V = length * width * height
    hours = len(t_out_night) or 1
    qs = []
    for r in t_out_night:
        dT = t_in - float(r["T"])
        n = effective_n(wind=r.get("wind"))
        qs.append(max(0.0, U * A * dT + VENT_COEF * n * V * dT))
    q_need = sum(qs) / len(qs) / 1000.0 if qs else 0.0
    pts = []
    for f in np.linspace(0, 1, 100):
        q = min(q_need * f, boiler_kw_max)
        E = q * hours
        gas = E / (LHV_GAS * BOILER_ETA) if E > 0 else 0.0
        share = (q / q_need) if q_need else 0.0
        hdd = 0.0
        for r in t_out_night:
            tin = float(r["T"]) + (t_in - float(r["T"])) * share
            if tin < float(t_crit):
                hdd += (float(t_crit) - tin)
        p = freeze_risk(max(0.0, hdd))
        m = margin(y_kg, price, drop_frac, gas, tariff, p)
        pts.append({"frac": round(float(f), 2), "gas_m3": round(float(gas), 1),
                    "cost_tg": round(float(gas * tariff), 0),
                    "p_freeze": p, "margin": m})
    return {"q_need_kw": round(q_need, 1), "boiler_kw_max": boiler_kw_max, "points": pts}
