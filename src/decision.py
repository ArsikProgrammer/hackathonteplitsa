"""Решение = код + экономика. LLM ничего не решает.

EV-правило (v2): heat если p_freeze*Loss > Cost.
Адаптивный порог p* = Cost/Loss вместо фиксированного 0.5.
Legacy decide() оставлен для совместимости.
"""
try:
    from .config import (P_FREEZE_THRESHOLD, P_DUMP_THRESHOLD,
                         READINESS_THRESHOLD, USE_EV_RULE)
except ImportError:
    from config import (P_FREEZE_THRESHOLD, P_DUMP_THRESHOLD,
                        READINESS_THRESHOLD, USE_EV_RULE)


def decide(v_gas_m3, cost_tg, p_freeze, loss_tg, p_dump, days_to_dump,
           readiness=0.85, p_freeze_thr=P_FREEZE_THRESHOLD,
           p_dump_thr=P_DUMP_THRESHOLD, readiness_thr=READINESS_THRESHOLD):
    """Legacy пороговое правило. Оставлено, но decide_ev предпочтительнее."""
    if p_freeze >= p_freeze_thr:
        action = "heat"
        reason = (f"p_freeze={p_freeze} >= {p_freeze_thr}: риск {loss_tg:,.0f} тг "
                  f"доминирует над {cost_tg:,.0f} тг")
    elif p_dump >= p_dump_thr and readiness >= readiness_thr:
        action = "sell_early"
        reason = (f"p_dump={p_dump} >= {p_dump_thr}: собрать до просадки (~{days_to_dump} дн.)")
    else:
        action = "hold"
        reason = (f"p_freeze={p_freeze} < {p_freeze_thr}, p_dump={p_dump} < {p_dump_thr}: держать")
    return {"action": action, "reason": reason, "v_gas_m3": v_gas_m3,
            "cost_tg": cost_tg, "p_freeze": p_freeze, "loss_tg": loss_tg,
            "p_dump": p_dump, "days_to_dump": days_to_dump, "readiness": readiness}


def decide_ev(cost_tg, p_freeze, loss_tg, p_dump=0.0, days_to_dump=0,
              readiness=0.85, readiness_thr=READINESS_THRESHOLD,
              v_gas_m3=0.0, profile="P1_flat"):
    """EV-решение. loss_tg = EV (матожидание, уже p*max). Не умножать на p!

    Возврат action + p_star + числа для вербализации.
    p_star = Cost/max где max выводится из EV/p (fallback EV если p=0).
    """
    ev_loss = float(loss_tg)
    pf = float(p_freeze)
    loss_max = float(loss_tg) / max(pf, 1e-9) if pf > 0 else float(loss_tg)
    p_star = float(cost_tg) / max(loss_max, 1e-9)
    p_star = min(max(p_star, 0.0), 1.0)
    if ev_loss > float(cost_tg):
        action = "heat"
        reason = (f"EV потерь {ev_loss:,.0f} > затрат {float(cost_tg):,.0f} "
                  f"(p*={p_star:.3f}): топить {profile}")
    elif float(p_dump) >= 0.6 and float(readiness) >= float(readiness_thr):
        action = "sell_early"
        reason = (f"p_dump={p_dump} индекс, готовность {readiness}: "
                  f"собрать до просадки (~{days_to_dump} дн.)")
    else:
        action = "hold"
        reason = (f"EV {ev_loss:,.0f} <= {float(cost_tg):,.0f}, "
                  f"p_dump={p_dump}: держать, пересчет 24ч")
    return {"action": action, "reason": reason, "v_gas_m3": v_gas_m3,
            "cost_tg": cost_tg, "p_freeze": p_freeze, "loss_tg": loss_tg,
            "p_dump": p_dump, "days_to_dump": days_to_dump,
            "readiness": readiness, "p_star": round(p_star, 4),
            "ev_loss_tg": round(ev_loss, 0), "profile": profile}


def margin(y_kg, price, drop_frac, gas_m3, gas_tariff, p_freeze):
    """Маржа тенге: выручка*(1-drop) - газ - риск."""
    revenue = float(y_kg) * float(price) * (1.0 - float(drop_frac))
    return round(revenue - float(gas_m3) * float(gas_tariff)
                 - float(p_freeze) * float(y_kg) * float(price), 0)
