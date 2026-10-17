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

    Понимает и xlsx, и старый формат .xls (stat.gov.kz отдаёт оба; .xls
    читается через xlrd). Ищет город по слову в шапке, возвращает
    DataFrame схемы price_risk. Огурцы/помидоры — строки с этими словами.
    Дату недели извлекает из заголовка («по состоянию на 31 октября 2023»).
    """
    import io
    import re
    if str(url_or_path).startswith("http"):
        import requests
        r = requests.get(url_or_path, timeout=60)
        r.raise_for_status()
        src = io.BytesIO(r.content)
    else:
        src = str(url_or_path)
    sheets = pd.read_excel(src, sheet_name=None, header=None)
    # лист «5» — средние цены; иначе последний лист
    target = "5" if "5" in sheets else list(sheets)[-1]
    raw = sheets[target].values
    rows = [[None if pd.isna(c) else c for c in row] for row in raw]
    if len(rows) < 5:
        raise ValueError(f"BNS sheet {target} too small")
    # дата недели из заголовка листа
    months = {"января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5,
              "июня": 6, "июля": 7, "августа": 8, "сентября": 9, "октября": 10,
              "ноября": 11, "декабря": 12}
    date = pd.NaT
    title = str(rows[0][0] or "")
    m = re.search(r"на (\d{1,2}) (\S+) (\d{4})", title)
    if m and m.group(2) in months:
        try:
            date = pd.Timestamp(int(m.group(3)), months[m.group(2)], int(m.group(1)))
        except Exception:
            date = pd.NaT
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
    df["date"] = date
    df["city"] = city
    df["import_m"] = np.nan
    df["tashkent_T"] = np.nan
    df["kzt_rub"] = np.nan
    df["holiday"] = 0
    return df


def build_features(df):
    """sin/cos + лаги t-1 и старше. Без подсмотра текущей недели."""
    df = df.copy().sort_values(["city", "crop", "week"]).reset_index(drop=True)
    # сезонность: реальная ISO-неделя из даты, fallback — порядковый week
    if "date" in df.columns:
        dts = pd.to_datetime(df["date"], errors="coerce")
        iso = dts.dt.isocalendar().week.astype(float)
        w = iso.fillna(df["week"].astype(float))
    else:
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
    """TimeSeriesSplit + RidgeCV + 2 baseline. Метрики и веса.
    Честная адаптация: полностью пустые признаки (import/курс/Ташкент, пока
    нет источников) отбрасываются и логируются — модель учится на реальных данных.
    """
    from sklearn.linear_model import RidgeCV
    from sklearn.preprocessing import StandardScaler
    from sklearn.model_selection import TimeSeriesSplit
    usable = [f for f in FEATURES if f in df.columns and df[f].notna().any()]
    dropped = [f for f in FEATURES if f not in usable]
    if not usable:
        usable, dropped = list(FEATURES), []
    df = df.dropna(subset=usable + [TARGET]).reset_index(drop=True)
    if len(df) < 30:
        return {"status": f"need>=30 rows, have {len(df)}", "n": len(df),
                "features_used": usable, "features_dropped": dropped}
    X = df[usable].values
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
    # прогноз следующей недели: лаги сдвигаются от последних наблюдений
    pred_next = None
    try:
        last = df.iloc[-1]
        row = {f: float(last[f]) for f in usable}
        w_next = float(last["week"]) + 1.0
        row["sin_w"] = float(np.sin(2 * np.pi * w_next / 52.0))
        row["cos_w"] = float(np.cos(2 * np.pi * w_next / 52.0))
        row["price_lag1"] = float(last[TARGET])
        row["price_lag2"] = float(last["price_lag1"])
        if "import_m" in df.columns and len(df) >= 2:
            v_new = df["import_m"].iloc[-1]
            if not pd.isna(v_new):
                row["import_lag2"] = float(v_new)
            v_old = df["import_m"].iloc[-2]
            if not pd.isna(v_old):
                row["import_lag3"] = float(v_old)
        if "kzt_rub" in df.columns:
            v_k = df["kzt_rub"].iloc[-1]
            if not pd.isna(v_k):
                row["kzt_rub_lag1"] = float(v_k)
        if "mean_price" in df.columns:
            row["spread_lag1"] = float(last[TARGET]) - float(last["mean_price"])
        row["holiday"] = 0.0  # будущий праздник неизвестен -> 0
        Xn = sc.transform(pd.DataFrame([row])[usable].values)
        pred_next = round(float(model.predict(Xn)[0]), 2)
    except Exception:
        pred_next = None
    out = {"status": "ok" if beats else "experimental:does-not-beat-lag",
           "n": len(df), "mae": mae, "mae_lag": mae_lag,
           "mae_seasonal": round(float(np.mean(maes_seas)), 2) if maes_seas else None,
           "resid_std": round(resid_std, 2), "pred_next": pred_next,
           "features_used": usable, "features_dropped": dropped,
           "coef": {k: round(float(v), 4) for k, v in zip(usable, model.coef_)},
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