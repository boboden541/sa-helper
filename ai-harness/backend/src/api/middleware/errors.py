"""Двухслойные ошибки API: человекочитаемая формулировка + технический блок (5.1.2 БФТ)."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from domain.model.validators import DomainError


class ApiError(Exception):
    """Ошибка с двумя слоями: message — человеку, tech — раскрывающийся блок."""

    def __init__(self, status_code: int, message: str, tech: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.tech = tech


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"message": exc.message, "techDetail": exc.tech or None},
    )


async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"message": exc.message, "techDetail": exc.tech or None, "field": exc.field or None},
    )
