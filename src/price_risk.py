"""Ценовой риск v2: только лаги, без утечек. Индекс 0-1, НЕ вероятность."""
import numpy as np
import pandas as pd
from pathlib import Path

try:
    from .config import DATA_DIR, DUMP_K, DUMP_X0, DROP_ALERT_FRAC
except ImportError:
    from config import DATA_DIR, DUMP_K, DUMP_X0, DROP_ALERT_FRAC

FEATURES = ["sin_w", "cos_w", "price_lag1", "price_lag2", "import_lag2",
            "import_lag3", "tashkent_T_avg3w", "kzt_rub_lag1", "spread_lag1", "holiday"]
TARGET = "taraz_price"


def load_bns_xlsx(url_or_path, city="Тараз"):
    """БНС недельник «Соцзначимые продтовары», лист 5 (средние цены).

    Качает xlsx по прямой ссылке или читает файл, ищет город по слову
    в шапке, возвращает DataFrame схемы price_risk.
    Огурцы/помидоры — строки, содержащие эти слова.
    """
    import openpyxl, io
    if str(url_or_path).startswith("http"):
        import requests
        r = requests.get(url_or_path, timeout=60)
        r.raise_for_status()
        wb = openpyxl.load_workbook(io.BytesIO(r.content), read_only=True, data_only=True)
    else:
        wb = openpyxl.load_workbook(url_or_path, read_only=True, data_only=True)
    # лист 5 — средние цены (судя по структуре), ищем по заголовку
    target_sheet = None
    for name in wb.sheetnames:
        if str(name).strip() == "5":
            target_sheet = name
            break
    if target_sheet is None:
        target_sheet = wb.sheetnames[-1]
    ws = wb[target_sheet]
    rows = list(ws.iter_rows(values_only=True))
    if len(rows) < 5:
        raise ValueError(f"BNS sheet {target_sheet} too small")
    # шапка: строка 3 (индекс 2) содержит города
    header = [str(c) if c else "" for c in rows[2]]
    ci = None
    for i, c in enumerate(header):
        if city in c:
            ci = i
            break
    if ci is None:
        raise ValueError(f"City {city} not in header: {header[:10]}")
    out = []
    for row in rows[3:]:
        name = str(row[0] or "")
        low = name.lower()
        if "огурцы" in low or "помидоры" in low:
            crop = "cucumber" if "огурцы" in low else "tomato"
            out.append({
                "crop": crop,
                "taraz_price": float(row[ci]) if row[ci] not in (None, "", "…") else np.nan,
                "mean_price": float(row[1]) if len(row) > 1 and row[1] not in (None, "", "…") else np.nan,
            })
    df = pd.DataFrame(out)
    if df.empty:
        raise ValueError("No cucumber/tomato rows in BNS sheet")
    # неделя подставим по порядку (добавить дату при необходимости)
    df["week"] = range(1, len(df) + 1)
    df["date"] = pd.NaT
    df["city"] = city
    df["import_m"] = np.nan
    df["tashkent_T"] = np.nan
    df["kzt_rub"] = np.nan
    df["holiday"] = 0
    return df


def build_features(df):
    """sin/cos + лаги t-1 и старше. Без подсмотра текущей недели."""
    df = df.copy().sort_values(["city", "crop", "week"]).reset_index(drop=True)
    w = df["week"].astype(float)
    df["sin_w"] = np.sin(2 * np.pi * w / 52.0)
    df["cos_w"] = np.cos(2 * np.pi * w / 52.0)
    g = df.groupby(["city", "crop"], group_keys=False)
    df["price_lag1"] = g[TARGET].shift(1)
    df["price_lag2"] = g[TARGET].shift(2)
    df["import_lag2"] = g["import_m"].shift(2) if "import_m" in df else np.nan
    df["import_lag3"] = g["import_m"].shift(3) if "import_m" in df else np.nan
    if "tashkent_T" in df:
        df["tashkent_T_avg3w"] = (
            g["tashkent_T"].transform(lambda s: s.rolling(3, min_periods=1).mean()).shift(1)
        )
    else:
        df["tashkent_T_avg3w"] = np.nan
    df["kzt_rub_lag1"] = g["kzt_rub"].shift(1) if "kzt_rub" in df else np.nan
    if "mean_price" in df:
        df["spread_lag1"] = g[TARGET].shift(1) - g["mean_price"].shift(1)
    else:
        df["spread_lag1"] = np.nan
    if "holiday" not in df:
        df["holiday"] = 0
    return df


def load_dataset(csv_path=None, crop="cucumber"):
    """Загрузка CSV схемы week,date,city,crop,taraz_price,mean_price,import_m,..."""
    from pathlib import Path
    if csv_path is None:
        csv_path = DATA_DIR / "prices_weekly.csv"
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(
            f"Нет {csv_path}. Скопируй TEMPLATE и заполни по stat.gov.kz.")
    df = pd.read_csv(csv_path)
    df = build_features(df)
    if "crop" in df:
        df = df[df["crop"] == crop].reset_index(drop=True)
    return df.dropna(subset=["price_lag1"]).reset_index(drop=True)



def train_ridge(df, use_gbm_resid=False):
    """TimeSeriesSplit + RidgeCV + 2 baseline. Метрики и веса."""
    from sklearn.linear_model import RidgeCV
    from sklearn.preprocessing import StandardScaler
    from sklearn.model_selection import TimeSeriesSplit
    df = df.dropna(subset=FEATURES + [TARGET]).reset_index(drop=True)
    if len(df) < 30:
        return {"status": f"need>=30 rows, have {len(df)}", "n": len(df)}
    X = df[FEATURES].values
    y = df[TARGET].values
    tss = TimeSeriesSplit(n_splits=min(5, len(df) // 10))
    maes, maes_lag, maes_seas = [], [], []
    for tr, te in tss.split(X):
        sc = StandardScaler().fit(X[tr])
        m = RidgeCV(alphas=np.logspace(-2, 3, 12)).fit(sc.transform(X[tr]), y[tr])
        pr = m.predict(sc.transform(X[te]))
        maes.append(float(np.mean(np.abs(y[te] - pr))))
        maes_lag.append(float(np.mean(np.abs(y[te] - df.loc[te, "price_lag1"].values))))
        idx = np.array(te) - 52
        valid = idx >= 0
        if valid.any():
            maes_seas.append(float(np.mean(np.abs(y[te][valid] - y[idx[valid]]))))
    sc = StandardScaler().fit(X)
    Xs = sc.transform(X)
    model = RidgeCV(alphas=np.logspace(-2, 3, 12)).fit(Xs, y)
    resid_std = float(np.std(y - model.predict(Xs)))
    mae = round(float(np.mean(maes)), 2)
    mae_lag = round(float(np.mean(maes_lag)), 2)
    beats = mae < mae_lag
    out = {"status": "ok" if beats else "experimental:does-not-beat-lag",
           "n": len(df), "mae": mae, "mae_lag": mae_lag,
           "mae_seasonal": round(float(np.mean(maes_seas)), 2) if maes_seas else None,
           "resid_std": round(resid_std, 2),
           "coef": {k: round(float(v), 4) for k, v in zip(FEATURES, model.coef_)},
           "intercept": round(float(model.intercept_), 2),
           "alpha": float(model.alpha_)}
    if use_gbm_resid:
        try:
            from sklearn.ensemble import HistGradientBoostingRegressor
            r = y - model.predict(Xs)
            gb = HistGradientBoostingRegressor(max_depth=2, max_iter=80).fit(X, r)
            out["gbm"] = {"used": True,
                "resid_var_explained": round(1 - float(np.var(r - gb.predict(X))) / max(float(np.var(r)), 1e-9), 3)}
        except Exception as e:
            out["gbm"] = {"used": False, "err": type(e).__name__}
    return out


def dump_risk_from_model(pred_price, base_price=None):
    """Прогноз -> индекс риска. p_dump 0-1 НЕ вероятность до калибровки."""
    base = float(base_price) if base_price else float(pred_price)
    drop = (base - float(pred_price)) / max(base, 1e-9)
    p = 1.0 / (1.0 + np.exp(-(drop * float(DUMP_K) - float(DUMP_X0))))
    p = float(min(max(p, 0.0), 1.0))
    days = 0 if drop <= float(DROP_ALERT_FRAC) else int(7 + min(max(drop, 0) * 40, 14))
    return {"pred_price": round(float(pred_price), 1), "drop_pct": round(drop * 100, 1),
            "p_dump": round(p, 3), "days_to_dump": days,
            "note": "индекс риска, требует калибровки Platt"}