"""AI-ассистент теплицы v1: LLM обязателен, но цифры считает только код.

Принцип: код считает (газ, деньги, риск), LLM понимает слова фермера
и объясняет решение. Любой ответ LLM проверяется на числа,
при расхождении — откат на шаблон.
"""
import os
import re
import json

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

ACTION_RU = {"heat": "топить", "sell_early": "собрать и сдать раньше", "hold": "держать режим"}

FALLBACK_TMPL_V2 = (
    "Решение: {action_ru} ({profile}). Газа: {v_gas_m3} м3 ({cost_tg} тг). "
    "Риск заморозка: {p_freeze}, потери под риском: {loss_tg} тг. "
    "Причина: {reason}"
)


def _env():
    return {
        "provider": os.getenv("LLM_PROVIDER", "").strip().lower(),
        "model": os.getenv("LLM_MODEL", "").strip(),
        "api_key": os.getenv("LLM_API_KEY", "").strip(),
        "base_url": os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").strip(),
        "anthropic_key": os.getenv("ANTHROPIC_API_KEY", "").strip(),
    }


def _call_openai_compatible(prompt, system="Ты точный вербализатор. Не меняй числа.", temperature=0.0):
    import requests
    e = _env()
    if not (e["model"] and e["api_key"]):
        raise RuntimeError("no-llm-config")
    r = requests.post(
        e["base_url"].rstrip("/") + "/chat/completions",
        headers={"Authorization": f"Bearer {e['api_key']}"},
        json={"model": e["model"], "temperature": temperature,
              "messages": [{"role": "system", "content": system},
                           {"role": "user", "content": prompt}]},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _call_anthropic(prompt, system="Ты точный вербализатор. Не меняй числа.", temperature=0.0):
    import anthropic
    e = _env()
    key = e["anthropic_key"] or (e["api_key"] if e["provider"] == "anthropic" else "")
    if not key:
        raise RuntimeError("no-anthropic-key")
    client = anthropic.Anthropic(api_key=key)
    msg = client.messages.create(
        model=e["model"] if e["provider"] == "anthropic" else "claude-3-5-sonnet-20241022",
        max_tokens=600, temperature=temperature,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in msg.content if hasattr(b, "text"))


def _call_llm(prompt, system="Ты точный вербализатор. Не меняй числа."):
    e = _env()
    if e["provider"] == "anthropic" or (e["anthropic_key"] and not e["api_key"]):
        return _call_anthropic(prompt, system)
    return _call_openai_compatible(prompt, system)


def validate_numbers(text, d):
    checks = [str(d.get("v_gas_m3")), str(d.get("p_freeze")), str(d.get("cost_tg"))]
    missing = [c for c in checks if c not in text]
    return {"ok": len(missing) == 0, "missing": missing}


def render_fallback_v2(d, options=None):
    base = FALLBACK_TMPL_V2.format(
        action_ru=ACTION_RU.get(d.get("action"), d.get("action")),
        profile=d.get("profile", "?"),
        v_gas_m3=d.get("v_gas_m3"), cost_tg=f'{d.get("cost_tg", 0):,.0f}',
        p_freeze=d.get("p_freeze"), loss_tg=f'{d.get("loss_tg", 0):,.0f}',
        reason=d.get("reason", ""))
    if options:
        parts = [f'{o["name"]}: {o["cost_tg"]:,.0f} тг, p={o["p_freeze"]}' for o in options]
        base += " Варианты — " + "; ".join(parts) + "."
    return base


# --- Понимание фермера словами ---
KEYWORDS_POOR = ["пыль", "песок", "сырой", "плохой", "зола", "шлак", "шымкент"]
KEYWORDS_GOOD = ["хороший", "качествен", "сортов", "чистый уголь"]
KEYWORDS_FOUL = ["забит", "сажа", "не чищен", "старый кот", "давление падает", "не тянет"]
KEYWORDS_CLEAN = ["почищен", "новый кот", "промыт", "чистый кот"]
KEYWORDS_GAS = ["газ"]
KEYWORDS_COAL = ["угол", "уголь"]
KEYWORDS_CUC = ["огурец", "огурц"]
KEYWORDS_TOM = ["томат", "помидор"]


def _keyword_extract(text):
    t = (text or "").lower()
    out = {"fuel": None, "coal_quality": None, "fouling": None,
           "crop": None, "readiness": None, "notes": []}
    if any(k in t for k in KEYWORDS_COAL):
        out["fuel"] = "coal"
    elif any(k in t for k in KEYWORDS_GAS):
        out["fuel"] = "gas"
    if any(k in t for k in KEYWORDS_POOR):
        out["coal_quality"] = "poor"
        out["notes"].append("poor-coal")
    elif any(k in t for k in KEYWORDS_GOOD):
        out["coal_quality"] = "good"
    if any(k in t for k in KEYWORDS_FOUL):
        out["fouling"] = 0.65
        out["notes"].append("fouled-boiler")
    elif any(k in t for k in KEYWORDS_CLEAN):
        out["fouling"] = 1.0
    m = re.search(r"готовност\w*\s*(\d{1,3})", t)
    if m:
        try:
            out["readiness"] = max(0.0, min(1.0, float(m.group(1)) / 100.0))
        except Exception:
            pass
    elif "пора собирать" in t or "спел" in t:
        out["readiness"] = 0.9
    elif "зелен" in t or "еще растет" in t or "ещё растет" in t:
        out["readiness"] = 0.5
    if any(k in t for k in KEYWORDS_CUC):
        out["crop"] = "cucumber"
    elif any(k in t for k in KEYWORDS_TOM):
        out["crop"] = "tomato"
    return out


def extract_farm_state(text, defaults=None):
    """Свободный текст фермера -> параметры для optimize_night.

    Сначала LLM JSON, при ошибке — keyword-fallback. Не падает никогда.
    Возврат: (params, meta), meta={source: llm|keywords|defaults}.
    """
    defaults = defaults or {"fuel": "gas", "coal_quality": "good", "fouling": 1.0,
                            "crop": "cucumber", "readiness": 0.85}
    params = dict(defaults)
    if not (text or "").strip():
        return params, {"source": "defaults", "raw": {}}
    try:
        e = _env()
        if e["model"] and (e["api_key"] or e["anthropic_key"]):
            prompt = (
                "Извлеки параметры теплицы из текста фермера. "
                "Верни СТРОГО JSON: "
                '{"fuel":"gas|coal","coal_quality":"good|poor","fouling":0.5-1.0,'
                '"crop":"cucumber|tomato","readiness":0.0-1.0}. '
                "Нет данных — null. Текст: " + text[:800]
            )
            raw = _call_llm(prompt, "Ты извлекаешь параметры. Отвечаешь только JSON.")
            m = re.search(r"\{.*\}", raw, re.S)
            data = json.loads(m.group(0) if m else raw)
            merged = {}
            for k in ("fuel", "coal_quality", "fouling", "crop", "readiness"):
                v = data.get(k)
                if v is None:
                    continue
                if k == "fouling":
                    try:
                        params[k] = max(0.4, min(1.0, float(v)))
                        merged[k] = params[k]
                    except Exception:
                        pass
                elif k == "readiness":
                    try:
                        params[k] = max(0.0, min(1.0, float(v)))
                        merged[k] = params[k]
                    except Exception:
                        pass
                elif isinstance(v, str) and v:
                    params[k] = v
                    merged[k] = v
            if merged:
                return params, {"source": "llm", "raw": merged}
    except Exception:
        pass
    kw = _keyword_extract(text)
    for k in ("fuel", "coal_quality", "fouling", "crop", "readiness"):
        if kw.get(k) is not None:
            params[k] = kw[k]
    return params, {"source": "keywords", "raw": kw}


def verbalize_v2(d, options=None, farmer_text=""):
    """Объяснение: почему best, а не остальные. Проверка чисел обязательна."""
    fallback = render_fallback_v2(d, options)
    try:
        e = _env()
        if not (e["model"] and (e["api_key"] or e["anthropic_key"])):
            return fallback + " [шаблон без LLM: нет ключа в .env]", False
        facts = json.dumps({"decision": d, "options": options or [],
                            "farmer_said": farmer_text}, ensure_ascii=False)[:3000]
        prompt = (
            "Ты агроном-объясняльщик для фермера. ЗАПРЕЩЕНО менять числа, "
            "добавлять новые числа, пересчитывать. Только числа из ФАКТОВ. "
            "Ответ 4-6 предложений, простой русский. "
            "Обязательно: повтори v_gas_m3, p_freeze, cost_tg без изменений, "
            "объясни почему выбранный профиль лучше остальных по деньгам и риску, "
            "и что делать сегодня ночью одним действием.\nФАКТЫ: " + facts
        )
        text = _call_llm(prompt)
        v = validate_numbers(text, d)
        if not v["ok"]:
            return fallback + f" [LLM отклонен: нет чисел {v['missing']}]", False
        return text, True
    except Exception as ex:
        return fallback + f" [fallback: {type(ex).__name__}]", False


def morning_brief(decision, price_info=None):
    """Утренняя сводка: топили/не топили + везти на базар или держать."""
    d = decision
    base = (f"Ночь: {ACTION_RU.get(d.get('action'), d.get('action'))}. "
            f"Затраты {d.get('cost_tg', 0):,.0f} тг, риск {d.get('p_freeze')}. ")
    if price_info:
        base += f"Цена: {price_info}."
    try:
        e = _env()
        if not (e["model"] and (e["api_key"] or e["anthropic_key"])):
            return base + " [шаблон без LLM]", False
        prompt = ("Сделай утреннюю сводку фермеру 2-3 предложения из ФАКТОВ, "
                  "числа не менять, повтори cost_tg и p_freeze как есть.\nФАКТЫ: "
                  + json.dumps(d, ensure_ascii=False)[:1500])
        text = _call_llm(prompt)
        v = validate_numbers(text, d)
        if not v["ok"]:
            return base + f" [LLM отклонен: нет {v['missing']}]", False
        return text, True
    except Exception as ex:
        return base + f" [fallback: {type(ex).__name__}]", False


def anomaly_guard(actual_gas_m3, model_gas_m3, p_freeze, note=""):
    """Сторожилка: если факт газа уходит от модели на 30%+ — подсвечивает.
    Возврат dict с флагом и текстом для ЛЛМ.
    """
    m = max(float(model_gas_m3), 1e-9)
    dev = abs(float(actual_gas_m3) - m) / m
    flag = dev > 0.30
    text = ""
    if flag:
        text = (f"Внимание: жжёте на {dev*100:.0f}% больше/меньше чем модель. "
                f"Причина: забитый котел, пленка или датчик. Риск {p_freeze}.")
    return {"flag": flag, "deviation": round(dev, 3), "note": text, "extra": note}


def price_verdict(taraz_price, mean_price, import_lag, p_dump, days_to_dump, readiness):
    """ИИ-конклюжн по импорту: стоит ли собирать раньше.
    Возврат dict с решением и текстом.
    """
    import_pressure = float(import_lag) > 0 if import_lag is not None else False
    spread = float(taraz_price) - float(mean_price)
    sell = (float(p_dump) >= 0.6 and float(readiness) >= 0.8) or (spread > 0 and import_pressure)
    reason = []
    if import_pressure:
        reason.append(f"импорт вырос ({import_lag}t), давит на цену")
    if spread > 0:
        reason.append(f"Тараз дороже средней на {spread:.0f} тг")
    if float(p_dump) >= 0.6:
        reason.append(f"индекс риска просадки {p_dump}")
    text = (" ; ".join(reason) if reason else "рынок стабилен")
    return {"sell_early": bool(sell), "spread": round(spread, 1),
            "import_pressure": bool(import_pressure), "text": text,
            "days_to_dump": int(days_to_dump)}

