"""Резолвер «Подключение ИИ» (СТ FNR-10): сохранённое → окружение → не задано.

Единственная точка, где живут:
  - имена переменных окружения провайдера (AI_BASE_URL / AI_MODEL / AI_TOKEN)
    — контракт fallback из UI-референса FNR-10;
  - стандартные переменные головного агента (ANTHROPIC_*), в которые параметры
    доставляются при запуске сессий (внешний контракт claude CLI);
  - реестр пресетов провайдеров (harness/providers.json — данные, не код:
    новый провайдер появляется без изменения логики).

Потребители: web-витрина (снимок состояния 4.2.1, проверка 4.2.3) и демон
(инъекция в окружение запускаемых сессий 4.3.2). Ошибка хранилища не
блокирует запуск сессии — инъекция возвращается пустой (СТ 4.3.2, ветвление
«хранилище недоступно при запуске»).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

PROTOCOLS = ("anthropic", "openai")

# контракт fallback-окружения (референс: подписи «пусто — из окружения»)
ENV_NAMES = {"base_url": "AI_BASE_URL", "model": "AI_MODEL", "token": "AI_TOKEN"}

# переменные головного агента, в которые инъекцируются параметры [ВНЕШНИЙ ФАКТ:
# имена читаются claude CLI; при смене контракта правится только здесь]
AGENT_ENV = {"base_url": "ANTHROPIC_BASE_URL",
             "token": "ANTHROPIC_AUTH_TOKEN",
             "model": "ANTHROPIC_MODEL"}

PRESETS_PATH = Path(__file__).resolve().parent / "providers.json"


def presets() -> list[dict]:
    """Реестр пресетов — хранимые данные; ошибка чтения → пустой список."""
    try:
        doc = json.loads(PRESETS_PATH.read_text(encoding="utf-8"))
        return [p for p in doc if p.get("provider") and p.get("protocol") in PROTOCOLS]
    except (OSError, ValueError):
        return []


def mask(token: str | None) -> str | None:
    """Маска токена для UI и журналов: полное значение наружу не попадает."""
    if not token:
        return None
    return "…" + token[-4:]


def mask_text(text: str, token: str | None) -> str:
    """Убрать токен из диагностических текстов (ответы провайдера, трассировки)."""
    if token and text:
        return text.replace(token, mask(token) or "…")
    return text


def load_saved(conn) -> dict:
    """Сохранённая строка настроек → dict; строки нет → пустой dict."""
    row = conn.execute("SELECT protocol, provider, base_url, model, token"
                       " FROM ai_settings WHERE id=1").fetchone()
    if row is None:
        return {}
    return {k: row[k] for k in ("protocol", "provider", "base_url", "model", "token")}


def effective(conn) -> dict:
    """Эффективные параметры и их источники: saved → env → unset.

    Возвращает {"protocol", "base_url", "model", "token", "sources"
    (поле → "saved"|"env"|"unset"), "token_source" ("saved"|"env"|"none")}.
    Ошибка хранилища трактуется как «настроек нет» (СТ 4.3.1, правило 5).
    """
    try:
        saved = load_saved(conn)
    except Exception:
        saved = {}
    out: dict = {"sources": {}}
    for field in ("protocol", "base_url", "model", "token"):
        val = saved.get(field)
        if val:
            src = "saved"
        else:
            env_name = ENV_NAMES.get(field)
            val = os.environ.get(env_name) if env_name else None
            src = "env" if val else "unset"
        out[field] = val
        out["sources"][field] = src
    out["token_source"] = (out["sources"]["token"]
                           if out["sources"]["token"] != "unset" else "none")
    return out


def session_env(conn) -> dict[str, str]:
    """Переопределения окружения для запускаемой сессии ({} — инъекции нет).

    anthropic: инъекция заданных полей (СТ 4.3.2: частичная конфигурация →
    инъекция заданного). openai (Фаза 2, СТ 4.4.2): сессии получают адрес
    шлюза протоколов как базовый URL — реальный адрес и токен провайдера
    знает только шлюз; шлюз поднимается здесь же и живёт с процессом.
    Ошибка старта шлюза → без инъекции (запуск не блокируется).
    """
    try:
        eff = effective(conn)
    except Exception:
        return {}
    if eff.get("protocol") == "anthropic":
        env: dict[str, str] = {}
        for field, name in AGENT_ENV.items():
            val = eff.get(field)
            if val:
                env[name] = val
        return env
    if eff.get("protocol") == "openai":
        import ai_gateway as gw  # лениво: без цикла импортов
        url = gw.ensure_for(eff)
        if url:
            env = {"ANTHROPIC_BASE_URL": url,
                   "ANTHROPIC_AUTH_TOKEN": "gateway-local"}
            if eff.get("model"):
                env["ANTHROPIC_MODEL"] = eff["model"]
            return env
    return {}


def apply_env(env: dict, conn) -> dict:
    """Дополнить окружение процесса параметрами подключения (мутирует env)."""
    try:
        env.update(session_env(conn))
    except Exception:
        pass
    return env
