"""Минимальный чат-клиент провайдера для Eve: anthropic + openai-совместимый.

Без SDK — простые POST через httpx; токен расшифрован только на момент вызова.
"""

from __future__ import annotations

import httpx


async def chat_call(protocol: str, url: str, model: str, token: str,
                    system: str, messages: list[dict], max_tokens: int = 8192) -> str:
    """Возвращает текст ответа модели. messages: [{role: user|assistant, content}].

    max_tokens 8192: рассуждающие модели (GLM и др.) тратят заметный бюджет на
    блок thinking — при 1024 до текста дело не доходило (stop_reason=max_tokens)."""
    url = (url or "").rstrip("/")
    async with httpx.AsyncClient(timeout=60) as client:
        if protocol == "anthropic":
            r = await client.post(
                f"{url}/v1/messages",
                headers={"x-api-key": token, "anthropic-version": "2023-06-01",
                         "content-type": "application/json"},
                json={"model": model, "max_tokens": max_tokens, "system": system,
                      "messages": messages})
        else:
            payload = {"model": model, "max_tokens": max_tokens,
                       "messages": [{"role": "system", "content": system}, *messages]}
            r = await client.post(f"{url}/chat/completions",
                headers={"Authorization": f"Bearer {token}",
                         "content-type": "application/json"},
                json=payload)
        r.raise_for_status()
        data = r.json()
    if protocol == "anthropic":
        texts = [b.get("text", "") for b in data.get("content", [])
                 if b.get("type") == "text"]
        return "".join(texts).strip()
    choices = data.get("choices", [])
    return ((choices[0].get("message") or {}).get("content") or "").strip() if choices else ""
