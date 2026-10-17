"""Сбор всех недельных xlsx с stat.gov.kz для обучения Ridge.
Страница: /ru/industries/economy/prices/spreadsheets/?name=19060&period=week
Ссылки: /api/iblock/element/ID/file/ru/ (прямые xlsx).
Запуск: python tools/fetch_bns_prices.py
"""
import sys
import re
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import requests
from price_risk import load_bns_xlsx
import pandas as pd

BASE = "https://stat.gov.kz"
LIST_URL = BASE + "/ru/industries/economy/prices/spreadsheets/?year=&name=19060&period=week&type="
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
OUT_DIR = Path("data/bns")
OUT_DIR.mkdir(parents=True, exist_ok=True)


def find_ids(html):
    ids = re.findall(r'/api/iblock/element/(\d+)/file/ru/', html)
    return list(dict.fromkeys(ids))


def download(eid, outpath):
    url = f"{BASE}/api/iblock/element/{eid}/file/ru/"
    r = requests.get(url, headers=UA, timeout=60, allow_redirects=True)
    r.raise_for_status()
    if r.content[:2] != b'PK':
        return False
    outpath.write_bytes(r.content)
    return True


def main():
    print("Загружаю страницу списка БНС...")
    r = requests.get(LIST_URL, headers=UA, timeout=60)
    r.raise_for_status()
    ids = find_ids(r.text)
    print(f"Найдено element ID: {len(ids)}")

    downloaded = 0
    for eid in ids:
        fname = OUT_DIR / f"bns_{eid}.xlsx"
        if fname.exists() or (OUT_DIR / f"bns_{eid}.xls").exists():
            continue
        try:
            if download(eid, fname):
                downloaded += 1
                if downloaded % 10 == 0:
                    print(f"  скачано {downloaded}...")
            else:
                fname.unlink(missing_ok=True)
        except Exception as e:
            print(f"  ERR {eid}: {type(e).__name__}")
        time.sleep(0.2)

    total = len(list(OUT_DIR.glob('bns_*.xlsx')))
    print(f"Скачано новых: {downloaded}. Всего файлов: {total}")

    rows = []
    for f in sorted(list(OUT_DIR.glob("bns_*.xlsx")) + list(OUT_DIR.glob("bns_*.xls"))):
        try:
            df = load_bns_xlsx(str(f), city="Тараз")
            df["source_file"] = f.name
            rows.append(df)
        except Exception:
            pass

    if not rows:
        print("Нет данных для парсинга")
        return

    all_data = pd.concat(rows, ignore_index=True)
    print(f"Всего строк из {len(rows)} файлов: {len(all_data)}")

    cuc = all_data[all_data["crop"] == "cucumber"].copy()
    print(f"Огурцов: {len(cuc)}")
    if len(cuc) >= 5:
        # реальные даты недель; одна дата = одна неделя (дубли файлов убираем по дате,
        # НЕ по цене — одинаковые цены разных недель это легитимный ряд)
        cuc["date"] = pd.to_datetime(cuc["date"], errors="coerce")
        cuc = cuc.sort_values(["date", "source_file"], na_position="last").reset_index(drop=True)
        dup = cuc["date"].notna() & cuc.duplicated(subset=["date"], keep="first")
        cuc = cuc[~dup].reset_index(drop=True)
        cuc["week"] = range(1, len(cuc) + 1)
        cuc.to_csv("data/prices_weekly.csv", index=False)
        print(f"Сохранено data/prices_weekly.csv: {len(cuc)} недель")
        print(cuc[["week", "date", "taraz_price", "mean_price"]].tail(10).to_string())
    else:
        print(f"Огурцов мало: {len(cuc)}")


if __name__ == "__main__":
    main()
