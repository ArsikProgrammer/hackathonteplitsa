"""Логистика: куда везти. Цены городов KZ (месячные, БНС) + расчёт рейса
под ТВОЮ машину (расход, вместимость, топливо, водитель, рефрижератор).

Допущения (честно помечены):
- дорога = прямая Хаверсина × 1.25 (трасса; можно заменить на 2ГИС API);
- скорость 70 км/ч; рефрижератор +2.5 л/ч генератора;
- возврат домой ПУСТЫМ (порожняк) — считается второй дорогой.
Маршрут — жадная эвристика «ближайший город с положительной маржой».
"""
import math
from functools import lru_cache
from pathlib import Path

try:
    from .config import DATA_DIR
except ImportError:
    from config import DATA_DIR

COORDS = {
    "Астана": (51.13, 71.43), "Алматы": (43.24, 76.95), "Шымкент": (42.30, 69.60),
    "Актау": (43.65, 51.19), "Актобе": (50.30, 57.17), "Атырау": (47.12, 51.88),
    "Жезказган": (48.80, 67.78), "Кокшетау": (53.28, 69.40), "Караганда": (49.80, 73.12),
    "Конаев": (43.25, 76.78), "Костанай": (53.22, 63.62), "Кызылорда": (44.80, 65.50),
    "Уральск": (51.20, 51.37), "Усть-Каменогорск": (49.95, 82.62),
    "Павлодар": (52.29, 76.96), "Петропавловск": (54.87, 69.16), "Семей": (50.40, 80.23),
    "Талдыкорган": (45.02, 78.37), "Тараз": (42.90, 71.36), "Туркестан": (43.30, 68.25),
}
ROAD_FACTOR = 1.25
AVG_SPEED_KMH = 70.0
REF_LPH = 2.5
MONTHS_RU = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль",
             "август", "сентябрь", "октябрь", "ноябрь", "декабрь"]


def haversine_km(a, b):
    """Расстояние между двумя точками (широта, долгота), км."""
    R = 6371.0
    p1, l1, p2, l2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    x = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin((l2 - l1) / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(x))


def road_km(city_a, city_b):
    """Километры по трассе между городами (прямая × 1.25)."""
    return haversine_km(COORDS[city_a], COORDS[city_b]) * ROAD_FACTOR


def trip_cost_tg(dist_km, capacity_kg, consum_l100, fuel_price,
                 return_empty=True, ref=False, driver_pay_per_day=0.0):
    """Стоимость рейса туда (+обратно порожняком). Допущения — в докстринге модуля."""
    dist_km = float(dist_km)
    hours = dist_km / AVG_SPEED_KMH
    liters = dist_km / 100.0 * float(consum_l100)
    if ref:
        liters += hours * REF_LPH
    days = max(1, math.ceil(hours / 24.0))
    one_way = liters * float(fuel_price) + float(driver_pay_per_day) * days
    total = one_way * (2.0 if return_empty else 1.0)
    return {"hours_one_way": round(hours, 1),
            "liters": round(liters, 1),
            "one_way_tg": round(one_way),
            "trip_tg": round(total),
            "cost_per_kg": round(total / max(float(capacity_kg), 1.0), 1)}


@lru_cache(maxsize=4)
def latest_city_prices(crop="cucumber", regional_dir=None):
    """Цены последнего месяца по всем городам из data/regional.
    Возврат: ((год, месяц), {город: цена_тг/кг}, средняя_по_КЗ)."""
    import re
    import pandas as pd
    key = "огурц" if crop == "cucumber" else "помидор"
    folder = Path(regional_dir) if regional_dir else (DATA_DIR / "regional")
    best = None
    for fp in folder.glob("reg_*.xlsx"):
        try:
            sheets = pd.read_excel(fp, sheet_name=None, header=None)
            v = sheets["1"].values
        except Exception:
            continue
        hrow = None
        for i in range(min(8, len(v))):
            if any(str(c).strip() == "Тараз" for c in v[i]):
                hrow = i
                break
        if hrow is None:
            continue
        hdr = [str(c).replace("\n", "").strip() for c in v[hrow]]
        month = None
        for cell in sheets.get("Обложка", pd.DataFrame()).values.ravel():
            t = str(cell).lower()
            if "дата" in t:
                continue
            for mi, mn in enumerate(MONTHS_RU):
                if mn in t:
                    m = re.search(r"(\d{4})", t)
                    if m:
                        month = (int(m.group(1)), mi + 1)
                    break
            if month:
                break
        if month is None:
            continue
        for i in range(hrow + 1, len(v)):
            if not str(v[i][0]).lower().startswith(key):
                continue
            prices, kz_avg = {}, None
            for h, val in zip(hdr, v[i]):
                try:
                    fv = float(val)
                except (TypeError, ValueError):
                    continue
                if h.startswith("Республика Казахстан"):
                    kz_avg = fv
                elif h in COORDS:
                    prices[h] = fv
            if prices and (best is None or month > best[0]):
                best = (month, prices, kz_avg)
    if best is None:
        raise FileNotFoundError(f"нет региональных данных в {folder}")
    return best


def rank_cities(crop="cucumber", capacity_kg=2000.0, consum_l100=22.0,
                fuel_price=280.0, return_empty=True, ref=False,
                driver_pay_per_day=0.0):
    """Ранжирование городов по чистой марже рейса под заданную машину."""
    month, prices, kz_avg = latest_city_prices(crop)
    home = prices.get("Тараз")
    if home is None:
        raise ValueError("нет цены Тараза")
    rows = []
    for city, price in prices.items():
        if city == "Тараз":
            continue
        km = road_km("Тараз", city)
        t = trip_cost_tg(km, capacity_kg, consum_l100, fuel_price,
                         return_empty=return_empty, ref=ref,
                         driver_pay_per_day=driver_pay_per_day)
        margin_kg = round(price - home - t["cost_per_kg"], 1)
        rows.append({"city": city, "price": price, "km": round(km),
                     "trip_tg": t["trip_tg"], "cost_kg": t["cost_per_kg"],
                     "margin_kg": margin_kg,
                     "margin_trip_tg": round(margin_kg * float(capacity_kg))})
    rows.sort(key=lambda r: -r["margin_kg"])
    return {"month": month, "home": home, "kz_avg": kz_avg, "rows": rows}


def greedy_route(rows, days_budget, capacity_kg=2000.0):
    """Жадный маршрут: ближайший город с положительной маржой, пока хватает суток.
    Ограничение — время в пути (срок годности огурца). Возврат домой обязателен.
    Маржа консервативна (каждый город как отдельный рейс с порожняком)."""
    pool = [r for r in rows if r["margin_kg"] > 0]
    if not pool:
        return {"legs": [], "total_km": 0, "days_used": 0.0, "margin_tg": 0}
    legs = []
    cur = "Тараз"
    total_km = 0.0
    hours_left = float(days_budget) * 24.0
    margin = 0.0
    while pool:
        pick = None
        for r in pool:
            km = road_km(cur, r["city"])
            if km / AVG_SPEED_KMH <= hours_left and (pick is None or km < pick[0]):
                pick = (km, r)
        if pick is None:
            break
        km, r = pick
        pool.remove(r)
        legs.append({"city": r["city"], "km": round(km), "margin_kg": r["margin_kg"]})
        total_km += km
        hours_left -= km / AVG_SPEED_KMH
        margin += r["margin_kg"] * float(capacity_kg)
        cur = r["city"]
    total_km += road_km(cur, "Тараз")  # возврат домой всегда
    return {"legs": legs, "total_km": round(total_km),
            "days_used": round(float(days_budget) - hours_left / 24.0, 1),
            "margin_tg": round(margin)}
