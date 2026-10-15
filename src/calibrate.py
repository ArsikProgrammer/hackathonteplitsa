"""Калибровка пары (U,N): beta=(X'X+lI)^-1 X'y. X=[[A*dT,V*dT]], y=Вт."""
import numpy as np
try:
    from .config import LHV_GAS, BOILER_ETA, VENT_COEF
except ImportError:
    from config import LHV_GAS, BOILER_ETA, VENT_COEF


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
    """Пара (U,N). Нужно >=7 ночей с разным ветром. cond>30 = коллинеарность."""
    rx, ry = [], []
    for r in records:
        dT = float(r["t_in"]) - float(r["t_out"])
        if dT <= 0:
            continue
        rx.append([float(A_env) * dT, float(V_m3) * dT])
        ry.append(float(r["v_gas_m3"]) * (LHV_GAS * BOILER_ETA) / max(float(r.get("hours", 10)), 1) * 1000.0)
    X = np.array(rx); y = np.array(ry); n = len(X)
    if n < 7:
        return {"U_hat": None, "N_hat": None, "status": "need>=7 nights", "n": n}
    XtX = X.T @ X + lam * np.eye(2)
    try:
        beta = np.linalg.solve(XtX, X.T @ y)
    except Exception:
        return {"U_hat": None, "N_hat": None, "status": "singular", "n": n}
    Uh, kh = float(beta[0]), float(beta[1])
    Nh = kh / float(VENT_COEF)
    resid = y - X @ beta
    s2 = float(resid @ resid) / max(n - 2, 1)
    try:
        cov = s2 * np.linalg.inv(XtX)
        seU, seN = float((max(cov[0, 0], 0)) ** 0.5), float((max(cov[1, 1], 0)) ** 0.5) / float(VENT_COEF)
        sv = np.linalg.svd(X, compute_uv=False)
        cond = float(sv[0] / max(sv[-1], 1e-12))
    except Exception:
        seU, seN, cond = float("nan"), float("nan"), float("nan")
    clip = not (2.0 <= Uh <= 8.0) or not (0.2 <= Nh <= 2.5)
    return {"U_hat": round(Uh, 2), "N_hat": round(Nh, 3), "se_U": round(seU, 3),
            "se_N": round(seN, 4), "cond": round(cond, 1), "n": n,
            "clipped": clip, "status": "ok" if cond < 30 else "ok:collinear-warn"}


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
