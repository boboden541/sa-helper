"""Общие помощники контроллеров журнала (расщепление journal.py, B2)."""

from __future__ import annotations

import functools
import logging

from api.middleware.errors import ApiError
from domain.model.validators import DomainError

log = logging.getLogger("api")


def _400(fn):
    import functools

    @functools.wraps(fn)  # сохраняем сигнатуру — иначе FastAPI требует query args/kw
    async def wrapper(*args, **kw):
        try:
            return await fn(*args, **kw)
        except DomainError as err:
            raise ApiError(400, err.message, tech=err.tech)
    return wrapper
