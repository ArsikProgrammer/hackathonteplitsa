"""Забор погоды Open-Meteo: прогноз + архив + кэш + интервал неопределенности."""
import json
import requests
from datetime import datetime, timedelta
from pathlib import Path

try:
    from .config import TARAZ_LAT, TARAZ_LON, TASHKENT_LAT, TASHKENT_LON, CACHE_DIR
except ImportError:
    from config import TARAZ_LAT, TARAZ_LON, TASHKENT_LAT, TASHKENT_LON, CACHE_DIR


def _cached_get(url, params, cache_key, ttl_hours=3):
    CACHE_DIR.mkdir(exist_ok=True)
    cp = CACHE_DIR / f"{cache_key}.json"
    if cp.exists():
        age = (datetime.now() - datetime.fromtimestamp(cp.stat().st_mtime)).total_seconds() / 3600
        if age < ttl_hours:
            return json.loads(cp.read_text(encoding="utf-8")), True
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    cp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data, False


def get_forecast(lat=TARAZ_LAT, lon=TARAZ_LON, days=2):
    """Прогноз почасовки. Возврат: список словарей t/T/RH/wind."""
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat, "longitude": lon,
        "hourly": "temperature_2m,relative_humidity_2m,wind_speed_10m",
        "forecast_days": days, "timezone": "Asia/Almaty",
    }
    try:
        data, from_cache = _cached_get(url, params, f"fc_{lat}_{lon}_{days}")
    except Exception:
        # fallback: последний кэш любой свежести
        cp = CACHE_DIR / f"fc_{lat}_{lon}_{days}.json"
        if cp.exists():
            data = json.loads(cp.read_text(encoding="utf-8"))
            from_cache = True
        else:
            raise
    h = data["hourly"]
    out = [
        {"time": t, "T": T, "RH": rh, "wind": w}
        for t, T, rh, w in zip(h["time"], h["temperature_2m"],
                               h["relative_humidity_2m"], h["wind_speed_10m"])
    ]
    return {"rows": out, "from_cache": from_cache}


def get_forecast_ensemble(lat=TARAZ_LAT, lon=TARAZ_LON, days=7):
    """Ансамбль Open-Meteo: mean + spread из разных моделей.
    Возврат rows со средним + spread для расчета вилки.
    """
    import numpy as np
    url = "https://ensemble-api.open-meteo.com/v1/ensemble"
    params = {
        "latitude": lat, "longitude": lon,
        "hourly": "temperature_2m,relative_humidity_2m,wind_speed_10m",
        "forecast_days": days, "timezone": "Asia/Almaty",
        "models": "icon_seamless,gfs_seamless,ecmwf_ifs",
    }
    data, from_cache = _cached_get(url, params, f"ens_{lat}_{lon}_{days}", ttl_hours=3)
    h = data["hourly"]
    times = h["time"]
    temps = h.get("temperature_2m")
    rhs = h.get("relative_humidity_2m")
    winds = h.get("wind_speed_10m")
    out = []
    for i, tstr in enumerate(times):
        t_vals = [m[i] for m in temps] if isinstance(temps[0], list) else [temps[i]]
        rh_vals = [m[i] for m in rhs] if isinstance(rhs[0], list) else [rhs[i]]
        w_vals = [m[i] for m in winds] if isinstance(winds[0], list) else [winds[i]]
        out.append({
            "time": tstr,
            "T": float(np.mean(t_vals)),
            "T_spread": float(np.std(t_vals)),
            "RH": float(np.mean(rh_vals)),
            "RH_spread": float(np.std(rh_vals)),
            "wind": float(np.mean(w_vals)),
            "members": len(t_vals),
        })
    n_models = len(temps) if isinstance(temps, list) else 1
    return {"rows": out, "from_cache": from_cache, "n_members": n_models}


def get_archive(lat, lon, start_date, end_date):
    """Архив для контрфакта. Даты 'YYYY-MM-DD'."""
    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude": lat, "longitude": lon, "start_date": start_date,
        "end_date": end_date, "hourly": "temperature_2m,relative_humidity_2m,wind_speed_10m",
        "timezone": "Asia/Almaty",
    }
    data, _ = _cached_get(url, params, f"ar_{lat}_{lon}_{start_date}_{end_date}", ttl_hours=24 * 30)
    h = data["hourly"]
    return [
        {"time": t, "T": T, "RH": rh, "wind": w}
        for t, T, rh, w in zip(h["time"], h["temperature_2m"],
                               h["relative_humidity_2m"], h["wind_speed_10m"])
    ]


def night_slice(rows, night_hours=(18, 19, 20, 21, 22, 23, 0, 1, 2, 3, 4, 5, 6)):
    """Отбор ночных часов из почасовки."""
    out = []
    for r in rows:
        try:
            hh = int(r["time"][11:13])
        except Exception:
            continue
        if hh in night_hours:
            out.append(r)
    return out


def forecast_with_spread(lat=TARAZ_LAT, lon=TARAZ_LON, spread=2.0):
    """Три сценария: base / cold / warm.
    Приоритет — ансамбль (честный spread из моделей), fallback — старый shift.
    """
    try:
        ens = get_forecast_ensemble(lat, lon)
        base = night_slice(ens["rows"])
        cold = []
        warm = []
        for r in base:
            s = float(r.get("T_spread", spread))
            cold.append({**r, "T": float(r["T"]) - s})
            warm.append({**r, "T": float(r["T"]) + s})
        return {
            "base": base, "cold": cold, "warm": warm,
            "spread": float(ens.get("n_members", 1)),
            "from_cache": ens["from_cache"],
            "source": "ensemble",
        }
    except Exception:
        fc = get_forecast(lat, lon)
        base = night_slice(fc["rows"])

        def shift(d):
            return [{**r, "T": r["T"] + d} for r in base]

        return {"base": base, "cold": shift(-spread), "warm": shift(spread),
                "spread": spread, "from_cache": fc["from_cache"], "source": "fallback"}
