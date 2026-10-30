"""Общие помощники контроллеров настроек (расщепление settings.py, B1)."""

from __future__ import annotations

from api.middleware.errors import ApiError
from domain.model.validators import DomainError


def _domain(fn):
    async def wrapper(*args, **kw):
        try:
            return await fn(*args, **kw)
        except DomainError as err:
            raise ApiError(err.status if hasattr(err, "status") else 400,
                           err.message, tech=err.tech)
    return wrapper
