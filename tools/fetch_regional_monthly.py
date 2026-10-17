"""Месячные розничные цены по регионам stat.gov.kz (name=19087).

Строки «Огурцы»/«Помидоры», столбцы «Тараз» и «Республика Казахстан».
Дата месяца берётся с обложки («Ноябрь 2022 года»).
Выход: data/prices_monthly.csv (схема weekly: date,crop,taraz_price,mean_price,...)
Запуск: python tools/fetch_regional_monthly.py
"""
import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from price_risk import load_bns_xlsx  # noqa: E402,F401  (проверка импорта не нужна)

LIST_URL = "https://stat.gov.kz/ru/industries/economy/prices/spreadsheets/?name=19087&year="
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
OUT_DIR = ROOT / "data" / "regional"
OUT_DIR.mkdir(parents=True, exist_ok=True)

MONTHS = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль",
          "август", "сентябрь", "октябрь", "ноябрь", "декабрь"]
PRODUCTS = {"огурц": "cucumber", "помидор": "tomato"}


def month_from_sheets(sheets):
    for name in ("Обложка", "Метаданные", "Содержание"):
        if name not in sheets:
            continue
        for row in sheets[name].values:
            for cell in row:
                t = str(cell).lower()
                m = re.search(r"(" + "|".join(MONTHS) + r")\w*\s+(\d{4})", t)
                if m and "дата" not in t:
                    mi = [i for i, x in enumerate(MONTHS)
                          if m.group(1).startswith(x[:4])][0]
                    return pd.Timestamp(int(m.group(2)), mi + 1, 15)
    return pd.NaT


def parse_file(path):
    sheets = pd.read_excel(path, sheet_name=None, header=None)
    sheet = "1" if "1" in sheets else None
    if sheet is None:
        for k, v in sheets.items():
            if len(v) > 40 and len(v[0]) > 15:
                sheet = k
                break
    if sheet is None:
        raise ValueError("no data sheet")
    v = sheets[sheet].values
    # шапка: строка, где есть «Тараз»
    hrow = None
    for i in range(min(8, len(v))):
        if any(str(c).strip() == "Тараз" for c in v[i]):
            hrow = i
            break
    if hrow is None:
        raise ValueError("no Taraz column")
    hdr = [str(c).replace("\n", "").strip() for c in v[hrow]]
    col_taraz = hdr.index("Тараз")
    col_kz = next((i for i, h in enumerate(hdr)
                   if h.startswith("Республика Казахстан")), None)
    date = month_from_sheets(sheets)
    out = []
    for i in range(hrow + 1, len(v)):
        name = str(v[i][0]).lower()
        for key, crop in PRODUCTS.items():
            if name.startswith(key):
                def val(j):
                    if j is None or j >= len(v[i]):
                        return float("nan")
                    x = v[i][j]
                    try:
                        return float(x)
                    except (TypeError, ValueError):
                        return float("nan")
                out.append({"date": date, "crop": crop,
                            "taraz_price": val(col_taraz),
                            "mean_price": val(col_kz)})
    if not out:
        raise ValueError("no product rows")
    return out


def main():
    r = requests.get(LIST_URL, headers=UA, timeout=20)
    r.raise_for_status()
    ids = list(dict.fromkeys(re.findall(
        r"/api/iblock/element/(\d+)/file/ru/", r.text)))
    print(f"ids={len(ids)}", flush=True)
    ok = fail = 0
    for eid in ids:
        fp = OUT_DIR / f"reg_{eid}.xlsx"
        if fp.exists():
            ok += 1
            continue
        try:
            rr = requests.get(
                f"https://stat.gov.kz/api/iblock/element/{eid}/file/ru/",
                headers=UA, timeout=30, allow_redirects=True)
            if rr.content[:2] != b"PK" or len(rr.content) < 5000:
                fail += 1
                continue
            fp.write_bytes(rr.content)
            ok += 1
        except Exception:
            fail += 1
        time.sleep(0.25)
    print(f"downloaded ok={ok} fail={fail}", flush=True)

    rows = []
    for fp in sorted(OUT_DIR.glob("reg_*.xlsx")):
        try:
            rows.extend(parse_file(fp))
        except Exception as e:
            pass
    df = pd.DataFrame(rows)
    df = df.dropna(subset=["taraz_price"])
    df = df.dropna(subset=["date"])
    df = df.drop_duplicates(subset=["date", "crop"], keep="first")
    df = df.sort_values(["crop", "date"]).reset_index(drop=True)
    df["city"] = "Тараз"
    df["week"] = df.groupby("crop").cumcount() + 1
    df["import_m"] = float("nan")
    df["tashkent_T"] = float("nan")
    df["kzt_rub"] = float("nan")
    df["holiday"] = 0
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")
    out = ROOT / "data" / "prices_monthly.csv"
    df[["crop", "taraz_price", "mean_price", "week", "date", "city",
        "import_m", "tashkent_T", "kzt_rub", "holiday"]].to_csv(out, index=False)
    print(f"saved {out.name}: rows={len(df)} "
          f"crops={df['crop'].value_counts().to_dict()} "
          f"span={df['date'].min()}..{df['date'].max()}", flush=True)


if __name__ == "__main__":
    main()
