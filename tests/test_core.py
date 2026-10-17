"""Yadro v2.1: 17 testov. Zapusk: python tests/test_core.py (pytest takzhe podhvatit)"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def test_physics():
    from physics import heat_balance
    r = heat_balance(50, 30, 4, "film", 18, [{"T": -5, "wind": 3}] * 12)
    assert 400 < r["V_gas_m3"] < 700, r
    assert r["Q_peak_kW"] > 0


def test_dynamics_stable():
    from dynamics import simulate_no_heat
    rows = [{"T": -5.0, "wind": 3.0, "time": f"T{h}"} for h in range(12)]
    r = simulate_no_heat(rows)
    assert -5 < r[-1]["T_in"] < 14, r[-1]
    assert r[-1]["T_soil"] < 16


def test_loss_coef():
    from dynamics import loss_coef
    g = loss_coef(50, 30, 4, "film")
    assert 10000 < g["G_W_per_K"] < 25000, g


def test_freeze_scale():
    from freeze import freeze_risk
    assert freeze_risk(10) < 0.15
    assert 0.4 < freeze_risk(60) < 0.6
    assert freeze_risk(112) > 0.85


def test_hdd():
    from freeze import hdd_deficit
    assert abs(hdd_deficit([{"T": 5}, {"T": 10}], t_crit=9.0) - 4.0) < 1e-9


def test_edge():
    from freeze import hdd_deficit, freeze_risk
    from calibrate import calibrate_UN
    assert hdd_deficit([]) == 0.0
    assert freeze_risk(0) == 0.047  # B=-3.0: p(0)=0.047 (полевая калибровка требуется)
    assert freeze_risk(10000) == 1.0
    r = calibrate_UN([{"t_in": 18, "t_out": 10, "v_gas_m3": 100, "hours": 12}] * 3, 2440, 6000)
    assert r["status"] == "need>=7 nights"


def test_dew():
    from freeze import dew_point_magnus
    assert -7 < dew_point_magnus(-5, 90) < -5


def test_fuel_order():
    from fuels import price_per_kwh
    g = price_per_kwh("gas")
    cp = price_per_kwh("coal", "poor", 0.7)
    assert g < 6 and cp > 15, (g, cp)


def test_boiler():
    from fuels import boiler_check
    assert boiler_check(382, 400)["feasible"]
    assert not boiler_check(500, 400)["feasible"]


def test_optimizer():
    from optimizer import optimize_night
    rows = [{"T": -5.0, "wind": 3.0, "time": f"2024-03-14T{h:02d}:00"}
            for h in (18, 19, 20, 21, 22, 23, 0, 1, 2, 3, 4, 5)]
    res = optimize_night(rows)
    assert res["best"]["name"] in ("P1_flat", "P2_econight", "P3_screen")
    assert res["saving_tg"] >= 0
    # p_noheat: холодная ночь без топки опаснее профиля
    assert 0.0 < res["p_noheat"] <= 1.0
    assert res["p_noheat"] >= res["best"]["p_freeze"], res
    # экран платный: в теплую ночь P3 не всегда best, свой экран дешевле нового
    warm = [{"T": -3.0, "wind": 3.0, "time": f"T{h}"} for h in range(12)]
    r_new = optimize_night(warm)
    r_own = optimize_night(warm, screen_owned=True)
    p3_new = [o for o in r_new["options"] if o["name"] == "P3_screen"][0]
    p3_own = [o for o in r_own["options"] if o["name"] == "P3_screen"][0]
    assert p3_new["screen_fee_tg"] == 4000.0, p3_new
    assert p3_own["screen_fee_tg"] == 500.0, p3_own
    assert p3_own["cost_tg"] < p3_new["cost_tg"]


def test_ev():
    from decision import decide_ev
    # loss_tg = EV (матожидание). heat если EV > cost.
    assert decide_ev(19173, 0.5, 2250000)["action"] == "heat"
    assert decide_ev(19173, 0.001, 4500)["action"] == "hold"
    # контракт optimizer->decision: EV=p*max, p* честный
    d = decide_ev(10504, 0.063, 283500)
    assert d["action"] == "heat" and abs(d["p_star"] - 0.0023) < 1e-3, d


def test_ev_marginal():
    from decision import decide_ev
    # маржинальный EV: тёплая ночь p_noheat ~ p_freeze -> держать
    d = decide_ev(14504, 0.047, 211500, p_noheat=0.047)
    assert d["action"] == "hold", d
    # холодная ночь: без топки p_noheat=0.9 -> топить
    d2 = decide_ev(14504, 0.047, 211500, p_noheat=0.9)
    assert d2["action"] == "heat" and d2["ev_saving_tg"] > 14504, d2


def test_decide_price():
    from decision import decide_price
    # индекс просадки высокий + урожай готов -> собрать раньше
    r = decide_price(500, 400, 25, 0.7, 8, 0.9)
    assert r["action"] == "sell_early" and r["sell_early"] is True
    # неделя не может ответить «топить»: только sell_early | hold
    r2 = decide_price(400, 400, 0, 0.1, 0, 0.5)
    assert r2["action"] == "hold" and r2["sell_early"] is False
    # незрелый урожай не собираем рано даже при риске
    r3 = decide_price(500, 400, 25, 0.7, 8, 0.5)
    assert r3["action"] == "hold"


def test_price_guard():
    from price_risk import train_ridge, dump_risk_from_model
    import pandas as pd
    df = pd.DataFrame({"sin_w": [0] * 5, "cos_w": [1] * 5,
                       "price_lag1": [1] * 5, "price_lag2": [1] * 5,
                       "import_lag2": [1] * 5, "import_lag3": [1] * 5,
                       "tashkent_T_avg3w": [1] * 5, "kzt_rub_lag1": [1] * 5,
                       "spread_lag1": [1] * 5, "holiday": [0] * 5,
                       "taraz_price": [1] * 5})
    assert "need>=30" in train_ridge(df)["status"]
    r = dump_risk_from_model(390, 410)
    assert 0 <= r["p_dump"] <= 1 and r["days_to_dump"] == 8


def test_simulate():
    from simulate import simulate
    r = simulate(50, 30, 4, "film", 18, [{"T": -5.0, "wind": 3.0}] * 12,
                 400, 15000, 300, 0.05)
    assert len(r["points"]) == 100
    assert r["points"][-1]["p_freeze"] <= r["points"][0]["p_freeze"]


def test_anomaly_guard():
    from ai_assistant import anomaly_guard
    # норма: отклонение <30% -> флаг False
    assert anomaly_guard(300, 300, 0.05)["flag"] is False
    # аномалия: +40% -> флаг True
    r = anomaly_guard(420, 300, 0.05)
    assert r["flag"] is True
    assert r["deviation"] == 0.4


def test_price_verdict():
    from ai_assistant import price_verdict
    # импорт давит + спред >0 -> продавать раньше
    r = price_verdict(500, 400, 25, 0.7, 8, 0.9)
    assert r["sell_early"] is True
    assert r["spread"] == 100.0
    assert r["import_pressure"] is True
    # стабильно -> не продавать
    r2 = price_verdict(400, 400, 0, 0.1, 0, 0.5)
    assert r2["sell_early"] is False


if __name__ == "__main__":
    tests = [test_physics, test_dynamics_stable, test_loss_coef, test_freeze_scale,
             test_hdd, test_edge, test_dew, test_fuel_order, test_boiler,
             test_optimizer, test_ev, test_ev_marginal, test_decide_price,
             test_price_guard, test_simulate, test_anomaly_guard, test_price_verdict]
    for t in tests:
        t()
        print(f"PASS {t.__name__}")
    print(f"ALL {len(tests)} PASS")
