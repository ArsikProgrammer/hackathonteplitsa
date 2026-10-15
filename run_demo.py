"""Сквозной прогон v2: динамика -> топливо -> оптимизатор -> EV -> текст."""
import sys
import io
from pathlib import Path

# Windows console: UTF-8 чтобы не ломало русский текст
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from config import DEMO_GREENHOUSE, T_TARGET_C, GAS_TARIFF_TG_M3
from optimizer import optimize_night
from decision import decide_ev
from ai_assistant import verbalize_v2

rows = [{"T": -3.0, "wind": 3.0, "RH": 85.0, "time": f"2024-03-14T{h:02d}:00"}
        for h in (18, 19, 20, 21, 22, 23, 0, 1, 2, 3, 4, 5)]
g = DEMO_GREENHOUSE
res = optimize_night(rows, g["length"], g["width"], g["height"], g["material"],
                     T_TARGET_C, "cucumber", "gas", "good", 1.0,
                     400.0, g["area_m2"], 10.0, 300.0, GAS_TARIFF_TG_M3)
best = res["best"]
d = decide_ev(best["cost_tg"], best["p_freeze"], best["loss_tg"],
              0.0, 0, 0.85, v_gas_m3=best["fuel_qty"], profile=best["name"])
text, used = verbalize_v2(d, options=res["options"])
print("BEST:", best)
print("SAVING:", res["saving_tg"])
print("DECISION:", d)
print("TEXT:", text, "| llm:", used)
