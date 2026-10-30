"""AES-256-GCM для токенов провайдеров (решение 3.1-12, НФТ-ah-8).

Ключ — из окружения (AI_HARNESS_TOKEN_KEY); расшифровка только на момент
вызова провайдера; в журналах — только маски.
"""

from __future__ import annotations

import base64
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from domain.model.validators import DomainError


def encrypt_token(key: bytes, plaintext: str) -> bytes:
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, plaintext.encode(), None)
    return nonce + ct


def decrypt_token(key: bytes, blob: bytes) -> str:
    nonce, ct = blob[:12], blob[12:]
    try:
        return AESGCM(key).decrypt(nonce, ct, None).decode()
    except InvalidTag:
        # Неверный ключ/данные: у cryptography InvalidTag — ПУСТОЕ исключение,
        # в логах демона выглядело как необъяснимый сбой прогона. Теперь это
        # DomainError с диагнозом → планировщик классифицирует как инфра-сбой
        # (детерминированный: ретрай бессмыслен) и блокирует с причиной.
        raise DomainError(
            "Не удалось расшифровать токен подключения — ключ "
            "AI_HARNESS_TOKEN_KEY изменился с момента сохранения; "
            "пересохраните подключение в настройках",
            tech="AESGCM InvalidTag") from None


def token_mask(token: str) -> str:
    """Хвост из 4 символов — единственное, что видно где-либо."""
    return "****" + token[-4:] if len(token) >= 4 else "****"
