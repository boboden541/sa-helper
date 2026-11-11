"""Путевые параметры URL: мусор в адресе — это 400 Bad Request, а не 500.

Раньше `uuid.UUID(path_param)` без обработки кидал ValueError и API отвечал
500 по всему семейству эндпоинтов (relations, connections, agents, projects,
alias-columns, runs log) — анализ 11.11.2026.
"""

from __future__ import annotations

import uuid

from api.middleware.errors import ApiError


def uuid_or_400(value: str, what: str = "идентификатор") -> uuid.UUID:
    """UUID из путевого параметра; мусор → ApiError 400 (не 500)."""
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        raise ApiError(400, f"{what}: неверный идентификатор") from None
