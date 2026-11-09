"""Мост LiteLLM: прогоны агентов через openai-подключения (Шаг 1 мультипротокола).

Claude Agent SDK говорит только Anthropic-протоколом; LiteLLM-сайдкар принимает
/v1/messages и переводит в chat/completions целевого провайдера (Google AI
Studio, OpenRouter, Groq, vLLM, Ollama). Демон рендерит конфиг маршрутов из
таблицы подключений; ключ провайдера живёт только внутри моста — SDK-процесс
его не видит. Изменение подключений → перезапись конфига + рестарт сайдкара
(редкое событие; in-flight openai-прогоны через мост при этом рвутся —
плановая цена синхронизации, ретрай-лестница демона их подхватывает).

Окружение демона: LITELLM_URL (адрес сайдкара для SDK), LITELLM_MASTER_KEY
(ключ моста для SDK), BRIDGE_CONFIG_PATH (куда писать config.yaml),
BRIDGE_CONTAINER (имя контейнера сайдкара для рестарта).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess

import sqlalchemy as sa
from repository.models import Connection
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger("daemon")

MODEL_PREFIX = "har-"
CONFIG_PATH = os.getenv("BRIDGE_CONFIG_PATH", "/app/bridge-config/config.yaml")
BRIDGE_CONTAINER = os.getenv("BRIDGE_CONTAINER", "ai-harness-litellm")


def render_config(rows: list[tuple[str, str, str, str]]) -> str:
    """config.yaml сайдкара. JSON — валидный YAML (без зависимости pyyaml).

    model_name = har-<id8> — точное имя, SDK присылает его в ANTHROPIC_MODEL;
    openai/<model> — целевая модель; drop_params не роняет запрос на
    антропик-специфичных параметрах SDK (thinking и пр.)."""
    doc = {
        "model_list": [
            {
                "model_name": f"{MODEL_PREFIX}{cid[:8]}",
                "litellm_params": {
                    "model": f"openai/{model}",
                    "api_base": url,
                    "api_key": token,
                },
            }
            for cid, url, model, token in rows
        ],
        "litellm_settings": {"drop_params": True},
    }
    return json.dumps(doc, ensure_ascii=False, indent=2)


async def sync_bridge(session: AsyncSession) -> str | None:
    """Рендер config.yaml по openai-подключениям; при изменении — рестарт
    сайдкара. Возвращает 'rendered', если конфиг перезаписан, иначе None.

    Хэш в app_setting обновляется ТОЛЬКО после успешного рестарта: упавший
    рестарт оставит хэш старым — следующий тик повторит (сайдкар жив, конфиг
    свежий на диске, но процесс не перечитал)."""
    conns = (
        (await session.execute(sa.select(Connection).where(Connection.protocol == "openai")))
        .scalars()
        .all()
    )
    from usecase.settings.connections import get_decrypted_token

    rows = [
        (str(c.id), c.url or "", c.model or "", await get_decrypted_token(session, c))
        for c in conns
    ]
    rendered = render_config(rows)
    digest = hashlib.sha256(rendered.encode()).hexdigest()
    stored = (
        await session.execute(
            sa.text("SELECT value FROM app_setting WHERE key='bridge:render_hash'")
        )
    ).scalar_one_or_none()
    if stored == digest:
        return None
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
        fh.write(rendered)
    subprocess.run(["docker", "restart", BRIDGE_CONTAINER], check=True, timeout=120)
    await session.execute(
        sa.text(
            "INSERT INTO app_setting (key, value) VALUES ('bridge:render_hash', :h) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
        ),
        {"h": digest},
    )
    await session.commit()
    log.info("мост LiteLLM: конфиг перезаписан, сайдкар %s перезапущен", BRIDGE_CONTAINER)
    return "rendered"
