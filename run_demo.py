"""Сквозной прогон v2: динамика -> топливо -> оптимизатор -> EV -> текст."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from config import DEMO_GREENHOUSE, T_TARGET_C, GAS_TARIFF_TG_M3
from optimizer import optimize_night
from decision import decide_ev
from llm_verbalizer import verbalize

rows = [{"T": -3.0, "wind": 3.0, "RH": 85.0, "time": f"2024-03-14T{h:02d}:00"}
        for h in (18, 19, 20, 21, 22, 23, 0, 1, 2, 3, 4, 5)]
g = DEMO_GREENHOUSE
res = optimize_night(rows, g["length"], g["width"], g["height"], g["material"],
                     T_TARGET_C, "cucumber", "gas", "good", 1.0,
                     400.0, g["area_m2"], 10.0, 300.0, GAS_TARIFF_TG_M3)
best = res["best"]
d = decide_ev(best["cost_tg"], best["p_freeze"], best["loss_tg"],
              0.0, 0, 0.85, v_gas_m3=best["fuel_qty"], profile=best["name"])
text, used = verbalize(d)
print("BEST:", best)
print("SAVING:", res["saving_tg"])
print("DECISION:", d)
print("TEXT:", text, "| llm:", used)
