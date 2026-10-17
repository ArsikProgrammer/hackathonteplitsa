"""Заполнение внешних признаков data/prices_weekly.csv:

- tashkent_T   — средняя дневная температура Ташкента за неделю (Open-Meteo archive)
- import_m     — импорт КЗ огурцов+помидоров (Comtrade, 0702+0707, мир, USD/мес)
- kzt_rub      — официальный курс KZT/RUB (RSS НБРК, на конец недели)

Запуск: python tools/fill_features.py
Все ответы кэшируются в .cache — повторный запуск мгновенный.
"""
import json
import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from config import TASHKENT_LAT, TASHKENT_LON, CACHE_DIR  # noqa: E402

CSV = ROOT / "data" / "prices_weekly.csv"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def cached_json(url, params, key, timeout=30):
    CACHE_DIR.mkdir(exist_ok=True)
    cp = CACHE_DIR / f"{key}.json"
    if cp.exists():
        return json.loads(cp.read_text(encoding="utf-8"))
    r = requests.get(url, params=params, headers=UA, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    cp.write_text(json.dumps(data), encoding="utf-8")
    time.sleep(0.25)
    return data


def tashkent_daily(start, end):
    j = cached_json(
        "https://archive-api.open-meteo.com/v1/archive",
        {"latitude": TASHKENT_LAT, "longitude": TASHKENT_LON,
         "start_date": start, "end_date": end,
         "daily": "temperature_2m_mean", "timezone": "Asia/Almaty"},
        f"tash_daily_{start}_{end}")
    d = j["daily"]
    return pd.Series(
        [float(x) if x is not None else float("nan") for x in d["temperature_2m_mean"]],
        index=pd.to_datetime(d["time"]))


def import_world_monthly():
    """Импорт КЗ (reporter 398) 0702+0707, мир (partnerCode=0), primaryValue USD."""
    CACHE_DIR.mkdir(exist_ok=True)
    vals = {}
    months = [f"{y}{m:02d}" for y in (2022, 2023, 2024, 2025, 2026)
              for m in range(1, 13) if (y, m) <= (2026, 9)]
    for code in ("0702", "0707"):
        for per in months:
            cp = CACHE_DIR / f"ct_{code}_{per}.json"
            if cp.exists():
                j = json.loads(cp.read_text(encoding="utf-8"))
            else:
                j = None
                for attempt in range(3):
                    try:
                        j = cached_json(
                            "https://comtradeapi.un.org/public/v1/preview/C/M/HS",
                            {"period": per, "reporterCode": "398",
                             "cmdCode": code, "flowCode": "M"},
                            f"ct_{code}_{per}", timeout=25)
                        break
                    except Exception:
                        time.sleep(1.5 * (attempt + 1))
                if j is None:
                    continue
            world = [x for x in j.get("data", []) if x.get("partnerCode") == 0]
            if world:
                v = float(world[0].get("primaryValue") or 0.0)
                vals[per] = vals.get(per, 0.0) + v
    return vals


def kzt_rub_on(date):
    """Курс KZT/RUB на дату из RSS НБРК (кэш по дате)."""
    CACHE_DIR.mkdir(exist_ok=True)
    cp = CACHE_DIR / f"nbk_{date:%Y%m%d}.xml"
    if cp.exists():
        txt = cp.read_text(encoding="utf-8")
    else:
        r = requests.get("https://nationalbank.kz/rss/get_rates.cfm",
                         params={"fdate": date.strftime("%d.%m.%Y")},
                         headers=UA, timeout=20)
        r.raise_for_status()
        txt = r.text
        cp.write_text(txt, encoding="utf-8")
        time.sleep(0.3)
    m = re.search(
        r"<title>\s*RUB\s*</title>\s*<description>([\d.,]+)</description>",
        txt, re.S)
    if not m:
        return float("nan")
    return float(m.group(1).replace(",", "."))


def main():
    import sys
    csv_path = Path(sys.argv[1]) if len(sys.argv) > 1 else CSV
    monthly = len(sys.argv) > 2 and sys.argv[2] == "monthly"
    df = pd.read_csv(csv_path)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    d0, d1 = df["date"].min(), df["date"].max()

    # 1. Ташкент: среднее за 7 дней, заканчивающихся на дату недели
    tser = tashkent_daily((d0 - pd.Timedelta(days=7)).strftime("%Y-%m-%d"),
                          d1.strftime("%Y-%m-%d"))
    df["tashkent_T"] = [
        round(float(tser[d - pd.Timedelta(days=6): d].mean()), 1)
        if tser[d - pd.Timedelta(days=6): d].notna().any() else float("nan")
        for d in df["date"]]

    # импорт: для недели — последний ЗАКРЫТЫЙ месяц; для месячных — свой месяц
    imp = import_world_monthly()

    def prev_month_key(d):
        y, m = (d.year, d.month - 1) if d.month > 1 else (d.year - 1, 12)
        return f"{y}{m:02d}"

    def imp_key(d):
        return f"{d.year}{d.month:02d}" if monthly else prev_month_key(d)
    df["import_m"] = [round(imp.get(imp_key(d), float("nan")) / 1e6, 2)
                      for d in df["date"]]  # млн USD
    # если какой-то месяц не пришёл (throttle) — берём последнее известное значение
    df["import_m"] = df["import_m"].ffill().bfill()

    # 3. Курс: на конец недели
    df["kzt_rub"] = [round(kzt_rub_on(d), 3) for d in df["date"]]

    out = df.copy()
    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    out.to_csv(csv_path, index=False)
    print("filled:",
          {c: int(out[c].notna().sum()) for c in ("tashkent_T", "import_m", "kzt_rub")},
          "of", len(out))


if __name__ == "__main__":
    main()
