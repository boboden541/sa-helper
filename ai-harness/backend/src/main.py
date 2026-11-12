"""Точка входа backend'а: FastAPI-приложение (uvicorn main:app)."""

from __future__ import annotations

from contextlib import asynccontextmanager

from api.middleware.errors import ApiError, api_error_handler, domain_error_handler
from config import get_settings
from database import dispose_engine
from domain.model.validators import DomainError
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    from database import get_engine

    get_engine()  # инициализация по конфигу
    yield
    await dispose_engine()


def create_app() -> FastAPI:
    # версия — из метаданных пакета (единый источник: pyproject.toml);
    # до установки пакета (pip install -e .) — фолбэк
    try:
        from importlib.metadata import version as _pkg_version

        app_version = _pkg_version("ai-harness")
    except Exception:  # noqa: BLE001 — метаданных может не быть (dev-запуск)
        app_version = "dev"
    app = FastAPI(title="AI-Harness", version=app_version, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        # источники — из окружения (BACKEND_CORS_ORIGINS, запятая — разделитель):
        # захардкоженный дев-origin Vite не взлетал на другом хосте деплоя
        allow_origins=[
            o.strip() for o in get_settings().backend_cors_origins.split(",") if o.strip()
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(DomainError, domain_error_handler)
    from api.controllers import auth, journal, settings, tasks, transitions

    @app.get("/api/v1/healthz", include_in_schema=False)
    async def healthz():
        # без обращения к БД: живость процесса для docker healthcheck
        return {"status": "ok"}

    app.include_router(tasks.router)
    app.include_router(transitions.router)
    app.include_router(auth.router)
    app.include_router(settings.router)
    app.include_router(journal.router)
    return app


app = create_app()
