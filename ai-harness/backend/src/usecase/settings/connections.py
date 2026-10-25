"""Подключения ИИ-провайдеров: CRUD, проверка без сохранения, активное (СТ §4.4.2)."""

from __future__ import annotations

import datetime as dt
import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from domain.model.validators import DomainError
from infrastructure.crypto.aesgcm import decrypt_token, encrypt_token, token_mask
from repository.models import Connection, ProviderPreset, User

REQUIRED = ("name", "url", "model", "token")


async def create_connection(session: AsyncSession, data: dict) -> Connection:
    for field in REQUIRED:
        if not data.get(field):
            raise DomainError(f"Не заполнено обязательное поле: {field}", field=field)
    if data.get("protocol") not in ("openai", "anthropic"):
        raise DomainError("Протокол: openai или anthropic", field="protocol")
    if (await session.execute(sa.select(sa.func.count()).select_from(Connection)
                              .where(Connection.name == data["name"]))).scalar_one():
        raise DomainError(f"Подключение с именем {data['name']!r} уже есть", field="name")

    conn = Connection(
        name=data["name"], protocol=data["protocol"], url=data["url"],
        model=data["model"],
        token_encrypted=encrypt_token(get_settings().token_key_bytes, data["token"]),
        token_tail=token_mask(data["token"]),
        check_status="unchecked",
    )
    session.add(conn)
    await session.commit()
    return conn


async def update_connection(session: AsyncSession, connection_id: uuid.UUID,
                            fields: dict) -> Connection:
    conn = await session.get(Connection, connection_id)
    if conn is None:
        raise DomainError("Подключение не найдено")
    for field in ("name", "url", "model", "protocol"):
        if field in fields and fields[field]:
            setattr(conn, field, fields[field])
    if fields.get("token"):
        conn.token_encrypted = encrypt_token(get_settings().token_key_bytes, fields["token"])
        conn.token_tail = token_mask(fields["token"])
        conn.check_status = "unchecked"
    await session.commit()
    return conn


async def delete_connection(session: AsyncSession, connection_id: uuid.UUID) -> None:
    conn = await session.get(Connection, connection_id)
    if conn is None:
        raise DomainError("Подключение не найдено")
    if conn.is_active:
        raise DomainError("Активное подключение нельзя удалить, пока не выбрано другое")
    await session.delete(conn)
    await session.commit()


async def activate_connection(session: AsyncSession, connection_id: uuid.UUID) -> None:
    conn = await session.get(Connection, connection_id)
    if conn is None:
        raise DomainError("Подключение не найдено")
    await session.execute(sa.update(Connection).values(is_active=False))
    conn.is_active = True
    conn.check_status = "active"
    await session.commit()


async def get_decrypted_token(session: AsyncSession, conn: Connection) -> str:
    """Расшифровка ТОЛЬКО на момент вызова провайдера (решение 3.1-12)."""
    return decrypt_token(get_settings().token_key_bytes, conn.token_encrypted)


async def check_connection(session: AsyncSession, data: dict) -> dict:
    """«Проверить» без сохранения: URL → токен → пробный запрос модели (ФТ-ah-60).

    Ошибки в два слоя: message человеку, techDetail копируется (ФТ-ah-61).
    """
    import httpx

    protocol = data.get("protocol")
    url = (data.get("url") or "").rstrip("/")
    token = data.get("token") or ""
    model = data.get("model") or ""
    if not url or not token or not model:
        raise DomainError("Для проверки нужны URL, токен и модель", field="url")

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            if protocol == "anthropic":
                r = await client.post(
                    f"{url}/v1/messages",
                    headers={"x-api-key": token, "anthropic-version": "2023-06-01",
                             "content-type": "application/json"},
                    json={"model": model, "max_tokens": 1,
                          "messages": [{"role": "user", "content": "ping"}]},
                )
            else:
                r = await client.get(f"{url}/models",
                                     headers={"Authorization": f"Bearer {token}"})
    except httpx.HTTPError as err:
        raise DomainError(
            "Не удалось связаться с провайдером. Проверьте адрес и сеть",
            tech=repr(err))

    if r.status_code in (401, 403):
        raise DomainError("Провайдер отклонил токен. Проверьте API-ключ и его права",
                          tech=f"HTTP {r.status_code}: {r.text[:300]}")
    if r.status_code == 404:
        raise DomainError("Метод API не найден. Проверьте URL и выбранный протокол",
                          tech=f"HTTP 404: {r.text[:300]}")
    if r.status_code == 429:
        raise DomainError("Лимит запросов исчерпан. Подождите или проверьте квоту токена",
                          tech="HTTP 429")
    if r.status_code >= 500:
        raise DomainError("Провайдер временно недоступен. Повторите проверку позже",
                          tech=f"HTTP {r.status_code}")
    if r.status_code >= 400:
        raise DomainError("Провайдер не принял запрос",
                          tech=f"HTTP {r.status_code}: {r.text[:300]}")
    return {"ok": True, "message": "Подключение успешно"}


async def list_presets(session: AsyncSession) -> list[ProviderPreset]:
    return list((await session.execute(
        sa.select(ProviderPreset).order_by(ProviderPreset.name))).scalars())
