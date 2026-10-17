"""Объяснимость через стандартизированные веса. Метод фиксирован.
Метод: вклад = |beta_i| * std(X_i) / sum. Без метода проценты запрещены.
"""
import numpy as np


def attribution(coef_dict, X_std_dict):
    num = {k: abs(float(v)) * float(X_std_dict.get(k, 1.0)) for k, v in coef_dict.items()}
    s = sum(num.values()) or 1.0
    return {k: round(v / s, 3) for k, v in sorted(num.items(), key=lambda x: -x[1])}
