"""LLM только вербализует готовое решение. Числа менять запрещено.
Контракт: числа из decision передаются как факты; ответ проверяется регуляркой.
Провайдер фиксируется в .env: LLM_PROVIDER, LLM_MODEL, LLM_API_KEY, LLM_BASE_URL.
Обязательный fallback без LLM.
"""
import os
import re
import json

FALLBACK_TMPL = (
    "Решение: {action_ru}. Газа: {v_gas_m3} м3 ({cost_tg} тг). "
    "Риск заморозка: {p_freeze}, потери под риском: {loss_tg} тг. "
    "Риск обвала цены: {p_dump} (~{days_to_dump} дн.). Причина: {reason}"
)
ACTION_RU = {"heat": "топить", "sell_early": "собрать и сдать раньше", "hold": "держать режим"}


def render_fallback(d):
    return FALLBACK_TMPL.format(
        action_ru=ACTION_RU.get(d.get("action"), d.get("action")),
        v_gas_m3=d.get("v_gas_m3"), cost_tg=f'{d.get("cost_tg", 0):,.0f}',
        p_freeze=d.get("p_freeze"), loss_tg=f'{d.get("loss_tg", 0):,.0f}',
        p_dump=d.get("p_dump"), days_to_dump=d.get("days_to_dump"),
        reason=d.get("reason", ""))


def validate_numbers(text, d):
    """Проверка: ключевые числа из решения присутствуют в тексте."""
    checks = [str(d.get("v_gas_m3")), str(d.get("p_freeze")), str(d.get("p_dump"))]
    missing = [c for c in checks if c not in text]
    return {"ok": len(missing) == 0, "missing": missing}


def build_prompt(d):
    facts = json.dumps(d, ensure_ascii=False)
    return (
        "Ты вербализатор решения для фермера. ЗАПРЕЩЕНО менять числа, добавлять новые числа, "
        "пересчитывать. Используй только числа из ФАКТОВ. Ответ 3-5 предложений, русский язык.\n"
        f"ФАКТЫ: {facts}\n"
        "Верни текст, где повторены v_gas_m3, p_freeze, p_dump без изменений."
    )


def verbalize(d, temperature=0.0):
    """Один вызов. При любой ошибке — fallback. Возврат (text, used_llm)."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass
    provider = os.getenv("LLM_PROVIDER", "").strip()
    model = os.getenv("LLM_MODEL", "").strip()
    api_key = os.getenv("LLM_API_KEY", "").strip()
    base_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").strip()
    if not (provider and model and api_key):
        return render_fallback(d), False
    try:
        import requests
        prompt = build_prompt(d)
        # OpenAI-совместимый endpoint (DeepSeek и аналоги поддерживают)
        r = requests.post(
            base_url.rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": model, "temperature": temperature,
                  "messages": [{"role": "system", "content": "Ты точный вербализатор. Не меняй числа."},
                               {"role": "user", "content": prompt}]},
            timeout=30,
        )
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"]
        v = validate_numbers(text, d)
        if not v["ok"]:
            return render_fallback(d) + f" [LLM ответ отклонен: нет чисел {v['missing']}]", False
        return text, True
    except Exception as e:
        return render_fallback(d) + f" [fallback: {type(e).__name__}]", False
