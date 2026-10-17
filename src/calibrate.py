"""Калибровка по ночным данным: beta=(X'X+lI)^-1 X'y.
Идентифицируемая схема: Q = G*dT + kW*dT*wind_eff (см. calibrate_UN)."""
import numpy as np
try:
    from .config import LHV_GAS, BOILER_ETA, VENT_COEF, AIR_EXCHANGE
except ImportError:
    from config import LHV_GAS, BOILER_ETA, VENT_COEF, AIR_EXCHANGE


def calibrate_U(records, A_env, lam=1.0):
    """Legacy: только U. Оставлена для совместимости."""
    xs, ys = [], []
    for r in records:
        dT = r["t_in"] - r["t_out"]
        if dT <= 0:
            continue
        xs.append(A_env * dT)
        ys.append(r["v_gas_m3"] * (LHV_GAS * BOILER_ETA) / max(r.get("hours", 10), 1) * 1000.0)
    X = np.array(xs).reshape(-1, 1); y = np.array(ys)
    if len(X) < 7:
        return {"U_hat": None, "status": "need>=7 nights", "n": len(X)}
    XtX = float(X.T @ X); Xty = float(X.T @ y)
    Uh = Xty / (XtX + lam)
    resid = y - X.flatten() * Uh
    se = float(np.sqrt((resid @ resid) / max(len(y) - 1, 1) / max(XtX, 1e-9)))
    return {"U_hat": round(float(Uh), 2), "se": round(se, 3), "n": len(X), "status": "ok"}


def calibrate_UN(records, A_env, V_m3, lam=1.0):
    """Калибровка по ночным данным — идентифицируемая параметризация.

    Старый вид X=[[A*dT, V*dT]] был коллинеарен ВСЕГДА (ratio V/A константа):
    U и N разделиться не могли, ветер в design matrix не входил.
    Теперь: Q = G*dT + kW*dT*wind_eff, где
      G   — итоговая теплоотдача Вт/К (стены + базовая вентиляция),
      kW  — ветровая доля (только при разном ветре между ночами),
      U   — выводится из G при фиксированном N=AIR_EXCHANGE: U=(G-0.33*N*V)/A.
    N отдельно из этих данных НЕ идентифицируем (физически: только сумма
    U*A+0.33*N*V наблюдаема) — возвращается фиксированным, честно помечен.
    Нужно >=7 ночей. cond>30 при наличии ветрового столбца = мало ветров."""
    xs, ys, winds = [], [], []
    for r in records:
        dT = float(r["t_in"]) - float(r["t_out"])
        if dT <= 0:
            continue
        w = r.get("wind")
        w_eff = 0.0
        if w is not None:
            w_eff = min(max((float(w) - 4.0) * 0.1, 0.0), 0.8)  # как в physics.effective_n
        xs.append([dT, dT * w_eff])  # схема: Q = G*dT + kW*dT*wind_eff
        ys.append(float(r["v_gas_m3"]) * (LHV_GAS * BOILER_ETA) / max(float(r.get("hours", 10)), 1) * 1000.0)
        winds.append(w_eff)
    X = np.array(xs); y = np.array(ys); n = len(X)
    if n < 7:
        return {"U_hat": None, "N_hat": None, "status": "need>=7 nights", "n": n}
    # ветровой столбец пуст (нет ветра или нет вариации) -> только G
    if not np.any(X[:, 1]):
        X = X[:, :1]
    XtX = X.T @ X + lam * np.eye(X.shape[1])
    try:
        beta = np.linalg.solve(XtX, X.T @ y)
    except Exception:
        return {"U_hat": None, "N_hat": None, "status": "singular", "n": n}
    G_hat = float(beta[0])
    resid = y - X @ beta
    s2 = float(resid @ resid) / max(n - X.shape[1], 1)
    try:
        cov = s2 * np.linalg.inv(XtX)
        seG = float(max(cov[0, 0], 0.0) ** 0.5)
        sv = np.linalg.svd(X, compute_uv=False)
        cond = float(sv[0] / max(sv[-1], 1e-12)) if X.shape[1] > 1 else 1.0
    except Exception:
        seG, cond = float("nan"), 1.0
    # U при фиксированном базовом N (не оцениваем — не идентифицируем из этих данных)
    U_hat = (G_hat - VENT_COEF * float(AIR_EXCHANGE) * float(V_m3)) / max(float(A_env), 1e-9)
    clip = not (2.0 <= U_hat <= 8.0)
    out = {"G_hat": round(G_hat, 1), "U_hat": round(U_hat, 2),
           "N_hat": float(AIR_EXCHANGE), "N_fixed": True,
           "kW_hat": round(float(beta[1]), 1) if X.shape[1] > 1 else 0.0,
           "se_G": round(seG, 1), "cond": round(cond, 1), "n": n,
           "clipped": clip, "status": "ok" if cond < 30 else "ok:collinear-warn",
           "note": "U выведен из G при базовом N; U и N по отдельности из газа не идентифицируемы"}
    return out


def calibrate_soil(night_series, C_soil_kwh=125.0):
    """Оценка hA почвы по остыванию. night_series: [{t_soil,t_in,t_soil_next,dt_h}]."""
    xs, ys = [], []
    CJ = float(C_soil_kwh) * 3_600_000.0
    for r in night_series:
        if "t_soil_next" not in r:
            continue
        dt = float(r.get("dt_h", 1.0)) * 3600.0
        xs.append(-(float(r["t_soil"]) - float(r["t_in"])) * dt / CJ)
        ys.append(float(r["t_soil_next"]) - float(r["t_soil"]))
    X = np.array(xs).reshape(-1, 1); y = np.array(ys)
    if len(X) < 5:
        return {"hA_hat": None, "status": "need>=5 hours", "n": len(X)}
    XtX = float(X.T @ X)
    if XtX < 1e-12:
        return {"hA_hat": None, "status": "no-variation", "n": len(X)}
    return {"hA_hat": round(float(X.T @ y) / XtX, 1), "n": len(X), "status": "ok"}
